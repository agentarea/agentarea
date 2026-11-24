package service

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/transport"
)

func jwt(claims map[string]any) string {
	raw, _ := json.Marshal(claims)
	enc := base64.RawURLEncoding.EncodeToString
	return enc([]byte(`{"alg":"none"}`)) + "." + enc(raw) + ".sig"
}

// issuer is a fake auth.openai.com: refresh answers rotate the refresh token.
type issuer struct {
	mu        sync.Mutex
	refreshes []string
	refuse    bool
	srv       *httptest.Server
}

func newIssuer(t *testing.T, now time.Time) *issuer {
	t.Helper()
	is := &issuer{}
	is.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		is.mu.Lock()
		defer is.mu.Unlock()
		body, _ := io.ReadAll(r.Body)
		switch r.URL.Path {
		case "/api/accounts/deviceauth/token":
			_, _ = io.WriteString(w, `{"authorization_code":"code","code_verifier":"ver"}`)
			return
		case "/oauth/token":
		default:
			w.WriteHeader(404)
			return
		}
		var req map[string]string
		_ = json.Unmarshal(body, &req)
		next := "r1"
		if req["grant_type"] == "refresh_token" {
			if is.refuse {
				w.WriteHeader(400)
				_, _ = io.WriteString(w, `{"error":"invalid_grant"}`)
				return
			}
			is.refreshes = append(is.refreshes, req["refresh_token"])
			next = req["refresh_token"] + "+"
		}
		raw, _ := json.Marshal(map[string]string{
			"access_token":  jwt(map[string]any{"exp": now.Add(time.Hour).Unix(), "n": next}),
			"refresh_token": next,
			"id_token":      jwt(map[string]any{"https://api.openai.com/auth": map[string]any{"chatgpt_account_id": "acc-1"}}),
		})
		_, _ = w.Write(raw)
	}))
	t.Cleanup(is.srv.Close)
	return is
}

type chatGPTEnv struct {
	*env
	is     *issuer
	config domain.Config
	secret string
}

func newChatGPTEnv(t *testing.T, backend string) *chatGPTEnv {
	t.Helper()
	e := newEnv(t)
	is := newIssuer(t, e.svc.d.Now())
	e.svc.d.ChatGPTIssuer = is.srv.URL
	prov := catalogapi.ProviderSpec{ID: uuid.New(), ProviderKey: "openai_codex", ProviderType: "openai_codex", Name: "ChatGPT",
		RequiresAPIKey: true, BaseURL: ptr(backend), Transport: domain.TransportResponses, Auth: domain.AuthChatGPT,
		ListShape: domain.ListDataID, ReasoningParam: domain.ReasoningEffortParam}
	e.cat.providers[prov.ID] = prov
	c := domain.Config{ID: uuid.NewString(), ProviderSpecID: prov.ID.String(), Name: "chatgpt", IsActive: true, WorkspaceID: e.ws.ID(), CreatedBy: "u1"}
	e.st.configs[c.ID] = c
	return &chatGPTEnv{env: e, is: is, config: c, secret: domain.OwnSecretName(c.ID)}
}

func (e *chatGPTEnv) store(t *testing.T, refresh string, expiresIn time.Duration) string {
	t.Helper()
	v := transport.ChatGPTTokens{AccessToken: "access-" + refresh, RefreshToken: refresh, AccountID: "acc-1",
		ExpiresAt: e.svc.d.Now().Add(expiresIn).Unix()}.Encode()
	e.sec.rows = append(e.sec.rows, &secretRow{ws: e.ws.ID(), name: e.secret, value: v, id: uuid.NewString()})
	return v
}

func (e *chatGPTEnv) stored(t *testing.T) transport.ChatGPTTokens {
	t.Helper()
	for _, r := range e.sec.rows {
		if r.name == e.secret {
			tok, err := transport.ParseChatGPTTokens(r.value)
			if err != nil {
				t.Fatal(err)
			}
			return tok
		}
	}
	t.Fatal("no stored sign-in")
	return transport.ChatGPTTokens{}
}

func TestAFreshSignInIsUsedWithoutARefresh(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	v := e.store(t, "r0", time.Hour)
	tok, err := e.svc.chatGPTAccess(context.Background(), e.ws, "u1", e.secret, v)
	if err != nil || tok.AccessToken != "access-r0" {
		t.Fatalf("tok=%+v err=%v", tok, err)
	}
	if len(e.is.refreshes) != 0 || e.st.locks != 0 {
		t.Errorf("refreshes=%v locks=%d", e.is.refreshes, e.st.locks)
	}
}

func TestAStaleSignInRefreshesOnceUnderTheLockAndKeepsTheRotatedToken(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	stale := e.store(t, "r0", time.Minute)
	tok, err := e.svc.chatGPTAccess(context.Background(), e.ws, "u1", e.secret, stale)
	if err != nil {
		t.Fatal(err)
	}
	if tok.RefreshToken != "r0+" || e.stored(t).RefreshToken != "r0+" || e.st.locks != 1 {
		t.Fatalf("tok=%+v stored=%+v locks=%d", tok, e.stored(t), e.st.locks)
	}
	// A second caller that read the stale set before the refresh landed finds
	// the new set under the lock: the spent refresh token is never sent again.
	again, err := e.svc.chatGPTAccess(context.Background(), e.ws, "u1", e.secret, stale)
	if err != nil || again.RefreshToken != "r0+" {
		t.Fatalf("again=%+v err=%v", again, err)
	}
	if len(e.is.refreshes) != 1 || e.is.refreshes[0] != "r0" {
		t.Errorf("refreshes = %v", e.is.refreshes)
	}
}

func TestARefusedRefreshAsksToSignInAgainAndKeepsTheStoredSet(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	stale := e.store(t, "r0", 0)
	e.is.refuse = true
	_, err := e.svc.chatGPTAccess(context.Background(), e.ws, "u1", e.secret, stale)
	if transport.PyType(err) != "ChatGPTSignInError" {
		t.Fatalf("err = %v", err)
	}
	if e.stored(t).RefreshToken != "r0" {
		t.Errorf("stored = %+v", e.stored(t))
	}
}

func TestANotSignedInConfigurationFailsLoud(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	_, err := e.svc.chatGPTAccess(context.Background(), e.ws, "u1", e.secret, "")
	if transport.PyType(err) != "ChatGPTSignInError" {
		t.Fatalf("err = %v", err)
	}
}

func TestFinishingTheSignInStoresTheTokenSetOnTheConfiguration(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	done, err := e.svc.FinishChatGPTSignIn(e.ctx, uuid.MustParse(e.config.ID), "dev", "CODE")
	if err != nil || !done {
		t.Fatalf("done=%v err=%v", done, err)
	}
	c := e.st.configs[e.config.ID]
	if c.APIKey == nil || *c.APIKey != e.secret || c.APIKeySecretID == nil { // pragma: allowlist secret
		t.Errorf("config = %+v", c)
	}
	if tok := e.stored(t); tok.RefreshToken != "r1" || tok.AccountID != "acc-1" {
		t.Errorf("stored = %+v", tok)
	}
}

func TestSignInRoutesRefuseAProviderWithAKey(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	c := domain.Config{ID: uuid.NewString(), ProviderSpecID: e.prov.ID.String(), Name: "openai", IsActive: true, WorkspaceID: e.ws.ID()}
	e.st.configs[c.ID] = c
	if _, err := e.svc.StartChatGPTSignIn(e.ctx, uuid.MustParse(c.ID)); err == nil {
		t.Fatal("a key provider started a ChatGPT sign-in")
	}
}

func TestACallOnAStaleSignInRefreshesAndCallsAsTheAccount(t *testing.T) {
	var header http.Header
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header = r.Header.Clone()
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: {\"type\":\"response.output_text.delta\",\"delta\":\"hi\"}\n\n"+
			"data: {\"type\":\"response.completed\",\"response\":{\"usage\":{\"input_tokens\":2,\"output_tokens\":1}}}\n\n")
	}))
	t.Cleanup(backend.Close)
	e := newChatGPTEnv(t, backend.URL)
	e.store(t, "r0", 0)
	m := api.ResolvedModel{ModelName: "gpt-x", ProviderType: "openai_codex", APIKeySecret: e.secret,
		Provider: api.ProviderProfile{BaseURL: backend.URL, Transport: domain.TransportResponses, Auth: domain.AuthChatGPT}}
	reply, err := e.svc.Call(context.Background(), api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"},
		api.Call{Model: m, Messages: []api.Message{{Role: "user", Content: "hi"}}})
	if err != nil {
		t.Fatal(err)
	}
	if reply.Content != "hi" || header.Get("Authorization") != "Bearer "+e.stored(t).AccessToken || header.Get("Chatgpt-Account-Id") != "acc-1" {
		t.Errorf("reply=%q auth=%q account=%q", reply.Content, header.Get("Authorization"), header.Get("Chatgpt-Account-Id"))
	}
	if e.stored(t).RefreshToken != "r0+" {
		t.Errorf("stored = %+v", e.stored(t))
	}
}
