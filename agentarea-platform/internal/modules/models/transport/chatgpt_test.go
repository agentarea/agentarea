package transport

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"
)

// fakeJWT is an unsigned JWT carrying claims, as the issuer's tokens are read.
func fakeJWT(claims map[string]any) string {
	raw, _ := json.Marshal(claims)
	enc := base64.RawURLEncoding.EncodeToString
	return enc([]byte(`{"alg":"none"}`)) + "." + enc(raw) + ".sig"
}

type issuerCall struct {
	path, contentType string
	body              []byte
}

func fakeIssuer(t *testing.T, answer func(path string, body []byte) (int, string)) (*httptest.Server, *[]issuerCall) {
	t.Helper()
	var calls []issuerCall
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		calls = append(calls, issuerCall{r.URL.Path, r.Header.Get("Content-Type"), body})
		status, out := answer(r.URL.Path, body)
		w.WriteHeader(status)
		_, _ = io.WriteString(w, out)
	}))
	t.Cleanup(srv.Close)
	return srv, &calls
}

var epoch = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

func auth(srv *httptest.Server) ChatGPTAuth {
	return ChatGPTAuth{Issuer: srv.URL, Transport: http.DefaultTransport, Now: func() time.Time { return epoch }}
}

func tokenAnswer(access, refresh string) string {
	raw, _ := json.Marshal(map[string]string{
		"access_token":  fakeJWT(map[string]any{"exp": epoch.Add(time.Hour).Unix(), "sub": access}),
		"refresh_token": refresh,
		"id_token":      fakeJWT(map[string]any{"https://api.openai.com/auth": map[string]any{"chatgpt_account_id": "acc-1"}}),
	})
	return string(raw)
}

func TestDeviceCodeStartReadsAStringInterval(t *testing.T) {
	srv, calls := fakeIssuer(t, func(string, []byte) (int, string) {
		return 200, `{"device_auth_id":"dev-1","user_code":"ABCD-EFGH","interval":"7"}`
	})
	d, err := auth(srv).StartDeviceCode(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if d != (DeviceCode{DeviceAuthID: "dev-1", UserCode: "ABCD-EFGH", VerificationURL: srv.URL + "/codex/device", Interval: 7}) {
		t.Errorf("device code = %+v", d)
	}
	if (*calls)[0].path != "/api/accounts/deviceauth/usercode" || string((*calls)[0].body) != `{"client_id":"app_EMoamEEZ73f0CkXaXp7hrann"}` {
		t.Errorf("call = %+v", (*calls)[0])
	}
}

func TestDevicePollIsPendingUntilTheCodeIsEnteredThenExchangesIt(t *testing.T) {
	entered := false
	srv, calls := fakeIssuer(t, func(path string, _ []byte) (int, string) {
		switch {
		case path == "/api/accounts/deviceauth/token" && !entered:
			return 403, `{"error":"pending"}`
		case path == "/api/accounts/deviceauth/token":
			return 200, `{"authorization_code":"code-1","code_challenge":"x","code_verifier":"ver-1"}`
		}
		return 200, tokenAnswer("a1", "r1")
	})
	a := auth(srv)
	if _, done, err := a.PollDeviceCode(context.Background(), "dev-1", "ABCD"); err != nil || done {
		t.Fatalf("pending poll: done=%v err=%v", done, err)
	}
	entered = true
	tok, done, err := a.PollDeviceCode(context.Background(), "dev-1", "ABCD")
	if err != nil || !done {
		t.Fatalf("poll: done=%v err=%v", done, err)
	}
	if tok.RefreshToken != "r1" || tok.AccountID != "acc-1" || tok.ExpiresAt != epoch.Add(time.Hour).Unix() {
		t.Errorf("tokens = %+v", tok)
	}
	ex := (*calls)[2]
	form, _ := url.ParseQuery(string(ex.body))
	if ex.path != "/oauth/token" || ex.contentType != "application/x-www-form-urlencoded" ||
		form.Get("grant_type") != "authorization_code" || form.Get("code") != "code-1" || form.Get("code_verifier") != "ver-1" ||
		form.Get("redirect_uri") != srv.URL+"/deviceauth/callback" || form.Get("client_id") != "app_EMoamEEZ73f0CkXaXp7hrann" {
		t.Errorf("exchange = %s %s %s", ex.path, ex.contentType, ex.body)
	}
}

func TestRefreshRotatesTheRefreshToken(t *testing.T) {
	srv, calls := fakeIssuer(t, func(string, []byte) (int, string) { return 200, tokenAnswer("a2", "r2") })
	old := ChatGPTTokens{AccessToken: "a1", RefreshToken: "r1", AccountID: "acc-1", ExpiresAt: epoch.Unix()}
	tok, err := auth(srv).Refresh(context.Background(), old)
	if err != nil {
		t.Fatal(err)
	}
	if tok.RefreshToken != "r2" || tok.AccessToken == "a1" || !tok.Fresh(epoch, 5*time.Minute) {
		t.Errorf("tokens = %+v", tok)
	}
	var sent map[string]string
	_ = json.Unmarshal((*calls)[0].body, &sent)
	if sent["grant_type"] != "refresh_token" || sent["refresh_token"] != "r1" || sent["client_id"] != "app_EMoamEEZ73f0CkXaXp7hrann" {
		t.Errorf("refresh body = %s", (*calls)[0].body)
	}
}

func TestARefusedRefreshAsksToSignInAgain(t *testing.T) {
	srv, _ := fakeIssuer(t, func(string, []byte) (int, string) {
		return 401, `{"error":{"code":"refresh_token_reused","message":"already used"}}`
	})
	_, err := auth(srv).Refresh(context.Background(), ChatGPTTokens{AccessToken: "a", RefreshToken: "r"})
	if PyType(err) != "ChatGPTSignInError" {
		t.Fatalf("err = %v (%s)", err, PyType(err))
	}
	if f, ok := Classify(err); !ok || f.Retryable || f.Cause != "provider_auth" {
		t.Errorf("failure = %+v", f)
	}
}

func TestAnUnavailableIssuerIsNotASignInError(t *testing.T) {
	srv, _ := fakeIssuer(t, func(string, []byte) (int, string) { return 503, `oops` })
	_, err := auth(srv).Refresh(context.Background(), ChatGPTTokens{AccessToken: "a", RefreshToken: "r"})
	var h *ProviderHTTPError
	if !errors.As(err, &h) || h.StatusCode != 503 {
		t.Fatalf("err = %v", err)
	}
}
