package service

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
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

// wire records every request a fake server got, headers and body as text.
type wire struct {
	mu   sync.Mutex
	seen []string
}

func (w *wire) record(r *http.Request) []byte {
	body, _ := io.ReadAll(r.Body)
	var b strings.Builder
	b.WriteString(r.Method + " " + r.URL.String() + "\n")
	for k, vs := range r.Header {
		b.WriteString(k + ": " + strings.Join(vs, ",") + "\n")
	}
	b.Write(body)
	w.mu.Lock()
	w.seen = append(w.seen, b.String())
	w.mu.Unlock()
	return body
}

func (w *wire) count() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return len(w.seen)
}

func (w *wire) carries(s string) bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	for _, x := range w.seen {
		if strings.Contains(x, s) {
			return true
		}
	}
	return false
}

// issuer is a fake auth.openai.com: refresh answers rotate the refresh token.
type issuer struct {
	wire
	refreshes []string
	refuse    bool
	pending   bool
	srv       *httptest.Server
}

func newIssuer(t *testing.T, now time.Time) *issuer {
	t.Helper()
	is := &issuer{}
	is.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body := is.record(r)
		is.mu.Lock()
		defer is.mu.Unlock()
		switch r.URL.Path {
		case "/api/accounts/deviceauth/usercode":
			_, _ = io.WriteString(w, `{"device_auth_id":"dev-1","user_code":"ABCD-EFGH","interval":"5"}`)
			return
		case "/api/accounts/deviceauth/token":
			if is.pending {
				w.WriteHeader(403)
				return
			}
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

// backend is a fake ChatGPT backend answering every call with one streamed reply.
func backend(t *testing.T) (*httptest.Server, *wire) {
	t.Helper()
	w := &wire{}
	srv := httptest.NewServer(http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
		w.record(r)
		rw.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(rw, "data: {\"type\":\"response.output_text.delta\",\"delta\":\"hi\"}\n\n"+
			"data: {\"type\":\"response.completed\",\"response\":{\"usage\":{\"input_tokens\":2,\"output_tokens\":1}}}\n\n")
	}))
	t.Cleanup(srv.Close)
	return srv, w
}

type chatGPTEnv struct {
	*env
	is      *issuer
	spec    catalogapi.ProviderSpec
	model   catalogapi.ModelSpec
	config  domain.Config
	secret  string
	backend string
}

func newChatGPTEnv(t *testing.T, backendURL string) *chatGPTEnv {
	t.Helper()
	e := newEnv(t)
	is := newIssuer(t, e.svc.d.Now())
	e.svc.d.ChatGPTIssuer = is.srv.URL
	prov := catalogapi.ProviderSpec{ID: uuid.New(), ProviderKey: "openai_codex", ProviderType: "openai_codex", Name: "ChatGPT",
		RequiresAPIKey: true, BaseURL: ptr(backendURL), Transport: domain.TransportResponses, Auth: domain.AuthChatGPT,
		ListShape: domain.ListDataID, ReasoningParam: domain.ReasoningEffortParam}
	e.cat.providers[prov.ID] = prov
	cw := 1000
	model := catalogapi.ModelSpec{ID: uuid.New(), ProviderSpecID: prov.ID, WorkspaceID: PlatformWorkspaceID,
		ModelName: "gpt-x", DisplayName: "GPT X", Kind: "chat", ContextWindow: &cw}
	e.cat.models[model.ID] = model
	c := domain.Config{ID: uuid.NewString(), ProviderSpecID: prov.ID.String(), Name: "chatgpt", IsActive: true, WorkspaceID: e.ws.ID(), CreatedBy: "u1"}
	e.st.configs[c.ID] = c
	return &chatGPTEnv{env: e, is: is, spec: prov, model: model, config: c, secret: domain.OwnSecretName(c.ID), backend: backendURL}
}

func (e *chatGPTEnv) store(t *testing.T, refresh string, expiresIn time.Duration) string {
	t.Helper()
	v := transport.ChatGPTTokens{AccessToken: "access-" + strings.ToUpper(refresh), RefreshToken: refresh, AccountID: "acc-1",
		ExpiresAt: e.svc.d.Now().Add(expiresIn).Unix()}.Encode()
	e.sec.rows = append(e.sec.rows, &secretRow{ws: e.ws.ID(), name: e.secret, value: v, id: uuid.NewString()})
	c := e.st.configs[e.config.ID]
	c.APIKey = &e.secret
	e.st.configs[c.ID] = c
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

func (e *chatGPTEnv) resolved() api.ResolvedModel {
	return api.ResolvedModel{ModelID: uuid.NewString(), ModelName: "gpt-x", ProviderType: "openai_codex", APIKeySecret: e.secret,
		ContextWindow: 1000, Provider: api.ProviderProfile{BaseURL: e.backend, Transport: domain.TransportResponses, Auth: domain.AuthChatGPT}}
}

func (e *chatGPTEnv) principal() api.Principal {
	return api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}
}

func TestAFreshSignInIsUsedWithoutARefresh(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	v := e.store(t, "r0", time.Hour)
	tok, err := e.svc.chatGPTAccess(context.Background(), e.ws, "u1", e.secret, v)
	if err != nil || tok.AccessToken != "access-R0" {
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

func TestACancelledCallStillSavesTheRotatedToken(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	stale := e.store(t, "r0", 0)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := e.svc.chatGPTAccess(ctx, e.ws, "u1", e.secret, stale); err != nil {
		t.Fatal(err)
	}
	if e.stored(t).RefreshToken != "r0+" {
		t.Errorf("stored = %+v", e.stored(t))
	}
}

func TestABusyLockWaitsNoFurtherAndRetriesLater(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	stale := e.store(t, "r0", 0)
	e.st.busy = true
	_, err := e.svc.chatGPTAccess(context.Background(), e.ws, "u1", e.secret, stale)
	if f, ok := transport.Classify(err); !ok || !f.Retryable {
		t.Fatalf("err = %v, failure = %+v", err, f)
	}
	if len(e.is.refreshes) != 0 {
		t.Errorf("refreshed while another call held the lock: %v", e.is.refreshes)
	}
	// The holder's renewal landed meanwhile: the waiter uses it.
	for _, r := range e.sec.rows {
		if r.name == e.secret {
			r.value = transport.ChatGPTTokens{AccessToken: "a2", RefreshToken: "r2", AccountID: "acc-1", ExpiresAt: e.svc.d.Now().Add(time.Hour).Unix()}.Encode()
		}
	}
	tok, err := e.svc.chatGPTAccess(context.Background(), e.ws, "u1", e.secret, stale)
	if err != nil || tok.RefreshToken != "r2" {
		t.Fatalf("tok=%+v err=%v", tok, err)
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

func TestTheSignInIsFinishedOnlyByWhoStartedItOnThatConfiguration(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	id := uuid.MustParse(e.config.ID)
	other := domain.Config{ID: uuid.NewString(), ProviderSpecID: e.spec.ID.String(), Name: "other", IsActive: true, WorkspaceID: e.ws.ID()}
	e.st.configs[other.ID] = other
	stranger := authn.WithCaller(context.Background(), authn.Caller{Principal: authn.Principal{UserID: "u9"}, Workspace: e.ws})

	if _, err := e.svc.FinishChatGPTSignIn(e.ctx, id); err == nil {
		t.Fatal("finished a sign-in nobody started")
	}
	d, err := e.svc.StartChatGPTSignIn(e.ctx, id)
	if err != nil || d.UserCode != "ABCD-EFGH" {
		t.Fatalf("start: %+v %v", d, err)
	}
	var br *BadRequestError
	if _, err := e.svc.FinishChatGPTSignIn(stranger, id); !errors.As(err, &br) {
		t.Fatalf("another member finished it: %v", err)
	}
	if _, err := e.svc.FinishChatGPTSignIn(e.ctx, uuid.MustParse(other.ID)); !errors.As(err, &br) {
		t.Fatalf("finished it on another configuration: %v", err)
	}
	e.is.pending = true
	if done, err := e.svc.FinishChatGPTSignIn(e.ctx, id); err != nil || done {
		t.Fatalf("pending: done=%v err=%v", done, err)
	}
	e.is.pending = false
	if done, err := e.svc.FinishChatGPTSignIn(e.ctx, id); err != nil || !done {
		t.Fatalf("done=%v err=%v", done, err)
	}
	c := e.st.configs[e.config.ID]
	if c.APIKey == nil || *c.APIKey != e.secret || c.APIKeySecretID == nil { // pragma: allowlist secret
		t.Errorf("config = %+v", c)
	}
	if tok := e.stored(t); tok.RefreshToken != "r1" || tok.AccountID != "acc-1" {
		t.Errorf("stored = %+v", tok)
	}
	if len(e.st.signIns) != 0 {
		t.Errorf("pending sign-ins left: %v", e.st.signIns)
	}
	if !e.is.carries(`"device_auth_id":"dev-1"`) {
		t.Error("the poll did not send the stored device code")
	}
}

func TestAnExpiredSignInCannotBeFinished(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	id := uuid.MustParse(e.config.ID)
	if _, err := e.svc.StartChatGPTSignIn(e.ctx, id); err != nil {
		t.Fatal(err)
	}
	start := e.svc.d.Now()
	e.svc.d.Now = func() time.Time { return start.Add(chatGPTDeviceCodeTTL) }
	var br *BadRequestError
	if _, err := e.svc.FinishChatGPTSignIn(e.ctx, id); !errors.As(err, &br) {
		t.Fatalf("err = %v", err)
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

func TestAChatGPTConfigurationTakesNoEndpoint(t *testing.T) {
	e := newChatGPTEnv(t, "http://unused")
	evil := "https://collector.example"
	var br *BadRequestError
	if _, err := e.svc.CreateConfig(e.ctx, domain.NewConfig{ProviderSpecID: e.spec.ID.String(), Name: "x", EndpointURL: &evil}); !errors.As(err, &br) {
		t.Fatalf("create: %v", err)
	}
	_, _, err := e.svc.UpdateConfig(e.ctx, uuid.MustParse(e.config.ID), domain.ConfigPatch{EndpointURL: domain.Opt[string]{Set: true, Value: &evil}})
	if !errors.As(err, &br) {
		t.Fatalf("update: %v", err)
	}
}

func TestACallOnAStaleSignInRefreshesAndCallsAsTheAccount(t *testing.T) {
	srv, seen := backend(t)
	e := newChatGPTEnv(t, srv.URL)
	e.store(t, "r0", 0)
	reply, err := e.svc.Call(context.Background(), e.principal(), api.Call{Model: e.resolved(), Messages: []api.Message{{Role: "user", Content: "hi"}}})
	if err != nil {
		t.Fatal(err)
	}
	if reply.Content != "hi" || !seen.carries("Authorization: Bearer "+e.stored(t).AccessToken) || !seen.carries("Chatgpt-Account-Id: acc-1") {
		t.Errorf("reply=%q seen=%v", reply.Content, seen.seen)
	}
	if e.stored(t).RefreshToken != "r0+" {
		t.Errorf("stored = %+v", e.stored(t))
	}
}

// No path puts the refresh token, or the stored token set, on the wire to a
// model host: chat and the test route send the access token only, at the
// catalog's address even when a stored endpoint names another; media,
// decisions and discovery refuse before reading the secret.
func TestNoPathSendsTheRefreshTokenToAModelHost(t *testing.T) {
	srv, seen := backend(t)
	collector, stolen := backend(t)
	e := newChatGPTEnv(t, srv.URL)
	refresh := "refresh-" + uuid.NewString()
	stored := e.store(t, refresh, time.Hour)
	c := e.st.configs[e.config.ID]
	c.EndpointURL = &collector.URL
	e.st.configs[c.ID] = c
	m := e.resolved()
	m.EndpointURL = collector.URL
	p := e.principal()

	if _, err := e.svc.Call(context.Background(), p, api.Call{Model: m, Messages: []api.Message{{Role: "user", Content: "hi"}}}); err != nil {
		t.Fatalf("chat: %v", err)
	}
	if r, err := e.svc.TestModel(e.ctx, uuid.MustParse(e.config.ID), e.model.ID, nil); err != nil || !r.Success {
		t.Fatalf("test route: %+v %v", r, err)
	}
	if seen.count() != 2 {
		t.Fatalf("model host saw %d calls, want 2", seen.count())
	}
	if _, err := e.svc.GenerateImage(context.Background(), p, api.ImageCall{Model: m, Prompt: "x"}); err == nil {
		t.Error("an image call ran on a ChatGPT sign-in")
	}
	if _, err := e.svc.Decide(context.Background(), p, api.Decision{Model: m, Questions: map[string]any{
		"q": map[string]any{"type": "choice", "instructions": "x", "criteria": map[string]any{"true": "y"}}}}); err == nil {
		t.Error("a decision ran on a ChatGPT sign-in")
	}
	if _, err := e.svc.DiscoverConfig(e.ctx, uuid.MustParse(e.config.ID)); err == nil {
		t.Error("discovery ran on a ChatGPT sign-in")
	}
	if seen.count() != 2 || stolen.count() != 0 {
		t.Errorf("model host calls = %d, stored endpoint calls = %d", seen.count(), stolen.count())
	}
	if seen.carries(refresh) || seen.carries(stored) {
		t.Error("a model host received the refresh token")
	}
	if !seen.carries("Authorization: Bearer access-" + strings.ToUpper(refresh)) {
		t.Error("the access token was not sent")
	}
}

func TestAResponsesLiteModelResolvesAndCallsTheLiteWay(t *testing.T) {
	srv, seen := backend(t)
	e := newChatGPTEnv(t, srv.URL)
	e.store(t, "r0", time.Hour)
	lite := e.model
	lite.ResponsesLite = true
	e.cat.models[lite.ID] = lite
	in := domain.Instance{ID: uuid.NewString(), ProviderConfigID: e.config.ID, ModelSpecID: lite.ID.String(), Name: "lite",
		IsActive: true, WorkspaceID: e.ws.ID(), Tags: []string{}}
	e.st.instances[in.ID] = in
	m, err := e.svc.Model(context.Background(), e.principal(), in.ID)
	if err != nil || !m.ResponsesLite {
		t.Fatalf("resolved %+v %v", m, err)
	}
	if _, err := e.svc.Call(context.Background(), e.principal(), api.Call{Model: m, Messages: []api.Message{{Role: "user", Content: "hi"}},
		Tools: []api.ToolDefinition{{Name: "ls"}}}); err != nil {
		t.Fatal(err)
	}
	if !seen.carries("X-Openai-Internal-Codex-Responses-Lite: true") || !seen.carries(`"type":"additional_tools"`) {
		t.Errorf("seen = %v", seen.seen)
	}
}
