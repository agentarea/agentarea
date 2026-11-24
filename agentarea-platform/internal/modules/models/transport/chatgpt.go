package transport

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// ChatGPT sign-in is the device-code login of the Codex CLI (codex-rs/login):
// its public client, its issuer, and the token set it keeps.
const (
	ChatGPTIssuer   = "https://auth.openai.com"
	chatGPTClientID = "app_EMoamEEZ73f0CkXaXp7hrann"
	// chatGPTOriginator names this harness to the ChatGPT backend, as third-party harnesses must.
	chatGPTOriginator = "agentarea"
	chatGPTAuthClaim  = "https://api.openai.com/auth"
	chatGPTBodyLimit  = 1 << 20
	chatGPTTimeout    = 30 * time.Second
)

// ChatGPTTokens is one sign-in's token set, stored as the configuration's secret.
// The refresh token rotates: every refresh answers a new one and the old one dies.
type ChatGPTTokens struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	IDToken      string `json:"id_token"`
	AccountID    string `json:"account_id"`
	// ExpiresAt is when the access token expires, Unix seconds.
	ExpiresAt int64 `json:"expires_at"`
}

// ParseChatGPTTokens reads a stored token set.
func ParseChatGPTTokens(stored string) (ChatGPTTokens, error) {
	var t ChatGPTTokens
	if err := json.Unmarshal([]byte(stored), &t); err != nil || t.AccessToken == "" || t.RefreshToken == "" {
		return ChatGPTTokens{}, SignInError("the stored ChatGPT sign-in is unreadable")
	}
	return t, nil
}

// Encode is the stored form.
func (t ChatGPTTokens) Encode() string {
	raw, _ := json.Marshal(t)
	return string(raw)
}

// Fresh: the access token outlives now by more than margin.
func (t ChatGPTTokens) Fresh(now time.Time, margin time.Duration) bool {
	return t.ExpiresAt > now.Add(margin).Unix()
}

// SignInError is a ChatGPT sign-in that cannot be used or renewed: only
// signing in again helps.
func SignInError(reason string) error {
	return &PyError{Type: "ChatGPTSignInError", Msg: "ChatGPT sign-in: " + reason + "; sign in with ChatGPT again in the provider settings"}
}

// chatGPTHeaders are what a ChatGPT sign-in adds to a model call.
func chatGPTHeaders(accountID string) map[string]string {
	return map[string]string{"chatgpt-account-id": accountID, "originator": chatGPTOriginator,
		"User-Agent": chatGPTOriginator, "Accept": "text/event-stream"}
}

// ChatGPTAuth is the sign-in's HTTP client against the issuer.
type ChatGPTAuth struct {
	Issuer    string
	Transport http.RoundTripper
	Now       func() time.Time
}

// DeviceCode is a started device-code login.
type DeviceCode struct {
	DeviceAuthID    string
	UserCode        string
	VerificationURL string
	Interval        int
}

func (a ChatGPTAuth) post(ctx context.Context, path, contentType string, body []byte) (int, []byte, error) {
	ctx, cancel := context.WithTimeout(ctx, chatGPTTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(a.Issuer, "/")+path, bytes.NewReader(body))
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Content-Type", contentType)
	resp, err := (&http.Client{Transport: a.Transport, CheckRedirect: NoRedirects}).Do(req)
	if err != nil {
		return 0, nil, classifyTransport(err, "read")
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, chatGPTBodyLimit))
	if err != nil {
		return 0, nil, classifyTransport(err, "read")
	}
	return resp.StatusCode, raw, nil
}

func (a ChatGPTAuth) postJSON(ctx context.Context, path string, v any) (int, []byte, error) {
	body, err := json.Marshal(v)
	if err != nil {
		return 0, nil, err
	}
	return a.post(ctx, path, "application/json", body)
}

// StartDeviceCode asks the issuer for a user code.
func (a ChatGPTAuth) StartDeviceCode(ctx context.Context) (DeviceCode, error) {
	status, raw, err := a.postJSON(ctx, "/api/accounts/deviceauth/usercode", map[string]string{"client_id": chatGPTClientID})
	if err != nil {
		return DeviceCode{}, err
	}
	if status != http.StatusOK {
		return DeviceCode{}, &ProviderHTTPError{StatusCode: status, ProviderMessage: errorBodyMessage(raw)}
	}
	var out struct {
		DeviceAuthID string          `json:"device_auth_id"`
		UserCode     string          `json:"user_code"`
		UserCodeAlt  string          `json:"usercode"`
		Interval     json.RawMessage `json:"interval"`
	}
	if err := json.Unmarshal(raw, &out); err != nil || out.DeviceAuthID == "" {
		return DeviceCode{}, &ProviderHTTPError{StatusCode: status, ProviderMessage: "the issuer answered no device code"}
	}
	code := out.UserCode
	if code == "" {
		code = out.UserCodeAlt
	}
	interval := 5
	if i, err := strconv.Atoi(string(bytes.Trim(out.Interval, `"`))); err == nil && i > 0 {
		interval = i
	}
	return DeviceCode{DeviceAuthID: out.DeviceAuthID, UserCode: code,
		VerificationURL: strings.TrimRight(a.Issuer, "/") + "/codex/device", Interval: interval}, nil
}

// PollDeviceCode checks whether the user entered the code; signed in, it
// answers the token set; false while the user has not.
func (a ChatGPTAuth) PollDeviceCode(ctx context.Context, deviceAuthID, userCode string) (ChatGPTTokens, bool, error) {
	status, raw, err := a.postJSON(ctx, "/api/accounts/deviceauth/token", map[string]string{"device_auth_id": deviceAuthID, "user_code": userCode})
	if err != nil {
		return ChatGPTTokens{}, false, err
	}
	if status == http.StatusForbidden || status == http.StatusNotFound {
		return ChatGPTTokens{}, false, nil
	}
	if status != http.StatusOK {
		return ChatGPTTokens{}, false, &ProviderHTTPError{StatusCode: status, ProviderMessage: errorBodyMessage(raw)}
	}
	var code struct {
		AuthorizationCode string `json:"authorization_code"`
		CodeVerifier      string `json:"code_verifier"`
	}
	if err := json.Unmarshal(raw, &code); err != nil || code.AuthorizationCode == "" {
		return ChatGPTTokens{}, false, &ProviderHTTPError{StatusCode: status, ProviderMessage: "the issuer answered no authorization code"}
	}
	form := url.Values{
		"grant_type": {"authorization_code"}, "code": {code.AuthorizationCode},
		"redirect_uri": {strings.TrimRight(a.Issuer, "/") + "/deviceauth/callback"},
		"client_id":    {chatGPTClientID}, "code_verifier": {code.CodeVerifier},
	}
	status, raw, err = a.post(ctx, "/oauth/token", "application/x-www-form-urlencoded", []byte(form.Encode()))
	if err != nil {
		return ChatGPTTokens{}, false, err
	}
	if status != http.StatusOK {
		return ChatGPTTokens{}, false, &ProviderHTTPError{StatusCode: status, ProviderMessage: errorBodyMessage(raw)}
	}
	t, err := a.tokens(raw, ChatGPTTokens{})
	return t, err == nil, err
}

// Refresh trades the refresh token for a new set. A refused refresh token
// (used, revoked or expired: any 4xx) is a SignInError.
func (a ChatGPTAuth) Refresh(ctx context.Context, old ChatGPTTokens) (ChatGPTTokens, error) {
	status, raw, err := a.postJSON(ctx, "/oauth/token", map[string]string{
		"client_id": chatGPTClientID, "grant_type": "refresh_token", "refresh_token": old.RefreshToken,
	})
	if err != nil {
		return ChatGPTTokens{}, err
	}
	if status >= 400 && status < 500 {
		return ChatGPTTokens{}, SignInError(fmt.Sprintf("the refresh was refused (HTTP %d: %s)", status, errorBodyMessage(raw)))
	}
	if status != http.StatusOK {
		return ChatGPTTokens{}, &ProviderHTTPError{StatusCode: status, ProviderMessage: errorBodyMessage(raw)}
	}
	return a.tokens(raw, old)
}

// tokens reads a token answer over prev: a field the answer leaves out keeps its value.
func (a ChatGPTAuth) tokens(raw []byte, prev ChatGPTTokens) (ChatGPTTokens, error) {
	var out struct {
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
		IDToken      string `json:"id_token"`
		ExpiresIn    int64  `json:"expires_in"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return ChatGPTTokens{}, SignInError("the issuer answered no tokens")
	}
	t := prev
	if out.AccessToken != "" {
		t.AccessToken = out.AccessToken
	}
	if out.RefreshToken != "" {
		t.RefreshToken = out.RefreshToken
	}
	if out.IDToken != "" {
		t.IDToken = out.IDToken
	}
	for _, token := range []string{t.IDToken, t.AccessToken} {
		auth, _ := jwtClaims(token)[chatGPTAuthClaim].(map[string]any)
		if acc, _ := auth["chatgpt_account_id"].(string); acc != "" {
			t.AccountID = acc
			break
		}
	}
	if t.AccessToken == "" || t.RefreshToken == "" {
		return ChatGPTTokens{}, SignInError("the issuer answered no access or refresh token")
	}
	if t.AccountID == "" {
		return ChatGPTTokens{}, SignInError("the sign-in names no ChatGPT account")
	}
	exp, _ := jwtClaims(t.AccessToken)["exp"].(float64)
	switch {
	case exp > 0:
		t.ExpiresAt = int64(exp)
	case out.ExpiresIn > 0:
		t.ExpiresAt = a.Now().Unix() + out.ExpiresIn
	default:
		return ChatGPTTokens{}, SignInError("the access token names no expiry")
	}
	return t, nil
}

// jwtClaims is a JWT's payload, unverified: the issuer handed it over TLS.
func jwtClaims(token string) map[string]any {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(strings.TrimRight(parts[1], "="))
	if err != nil {
		return nil
	}
	var claims map[string]any
	if json.Unmarshal(raw, &claims) != nil {
		return nil
	}
	return claims
}
