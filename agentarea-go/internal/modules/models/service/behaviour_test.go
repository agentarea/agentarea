package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/transport"
)

func (e *env) config(ws string, endpoint string, managed *string) domain.Config {
	id := uuid.NewString()
	c := domain.Config{ID: id, ProviderSpecID: e.prov.ID.String(), Name: "cfg", IsActive: true, WorkspaceID: ws,
		CreatedBy: "u1", ManagedBy: managed}
	if endpoint != "" {
		c.EndpointURL = &endpoint
	}
	name := domain.OwnSecretName(id)
	c.APIKey = &name
	e.sec.rows = append(e.sec.rows, &secretRow{ws: ws, name: name, value: "sk-secret-" + ws[:4], id: uuid.NewString()})
	e.st.configs[id] = c
	return c
}

func (e *env) instance(ws string, c domain.Config, spec uuid.UUID) string {
	id := uuid.NewString()
	e.st.instances[id] = domain.Instance{ID: id, ProviderConfigID: c.ID, ModelSpecID: spec.String(), Name: "i",
		IsActive: true, WorkspaceID: ws, Tags: []string{}}
	return id
}

func sse(w http.ResponseWriter, events ...string) {
	w.Header().Set("Content-Type", "text/event-stream")
	for _, ev := range events {
		_, _ = fmt.Fprintf(w, "data: %s\n\n", ev)
		w.(http.Flusher).Flush()
	}
}

// openAIReplay is a recorded chat-completions stream: reasoning, text, a tool call, usage with cost.
func openAIReplay(seen *http.Request) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		*seen = *r.Clone(context.Background())
		sse(w,
			`{"id":"c1","choices":[{"index":0,"delta":{"role":"assistant","reasoning_content":"think"}}]}`,
			`{"id":"c1","choices":[{"index":0,"delta":{"content":"Hel"}}]}`,
			`{"id":"c1","choices":[{"index":0,"delta":{"content":"lo"}}]}`,
			`{"id":"c1","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"f","arguments":"{\"a\":1}"}}]}}]}`,
			`{"id":"c1","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}`,
			`{"id":"c1","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15,"cost":0.0025}}`,
			`[DONE]`)
	}
}

func TestCreateConfigKeepsTheKeyByReference(t *testing.T) {
	e := newEnv(t)
	v, err := e.svc.CreateConfig(e.ctx, domain.NewConfig{ProviderSpecID: e.prov.ID.String(), Name: "mine", APIKey: ptr("sk-live")})
	if err != nil {
		t.Fatal(err)
	}
	own := domain.OwnSecretName(v.ID)
	if v.APIKey == nil || *v.APIKey != own || v.APIKeySecretID == nil {
		t.Fatalf("config holds %v / %v, want the reference %s", v.APIKey, v.APIKeySecretID, own)
	}
	if got, _ := (fakeManager{e.sec, e.ws.ID()}).Get(context.Background(), own); got != "sk-live" {
		t.Fatalf("secret value %q", got)
	}
	if refs := e.sec.refs[v.ID]; len(refs) != 1 || refs[0].SecretID != *v.APIKeySecretID || refs[0].Field != "api_key" {
		t.Fatalf("references %+v", refs)
	}
	if strings.Contains(fmt.Sprintf("%+v", v), "sk-live") {
		t.Fatal("the view carries the key")
	}
}

func TestCreateConfigRefusals(t *testing.T) {
	e := newEnv(t)
	managedBy := "connections"
	e.sec.rows = append(e.sec.rows, &secretRow{ws: e.ws.ID(), name: "conn", value: "x", id: "s-owned", ownerType: &managedBy})
	cases := map[string]struct {
		n    domain.NewConfig
		want string
	}{
		"unknown spec":     {domain.NewConfig{ProviderSpecID: uuid.NewString(), Name: "x"}, "Provider spec not found"},
		"private endpoint": {domain.NewConfig{ProviderSpecID: e.prov.ID.String(), Name: "x", EndpointURL: ptr("http://127.0.0.1:9")}, EndpointNotAllowed},
		"unknown secret":   {domain.NewConfig{ProviderSpecID: e.prov.ID.String(), Name: "x", APIKeySecretID: ptr("nope")}, "No secret nope in this workspace"},
		"owned secret":     {domain.NewConfig{ProviderSpecID: e.prov.ID.String(), Name: "x", APIKeySecretID: ptr("s-owned")}, "Secret 'conn' is managed by connections and cannot be reused as a provider API key."},
	}
	for name, c := range cases {
		if _, err := e.svc.CreateConfig(e.ctx, c.n); err == nil || err.Error() != c.want {
			t.Errorf("%s: %v, want %q", name, err, c.want)
		}
	}
	e.admin = errors.New("not admin")
	if _, err := e.svc.CreateConfig(e.ctx, domain.NewConfig{ProviderSpecID: e.prov.ID.String(), Name: "x"}); err == nil || err.Error() != "not admin" {
		t.Fatalf("admin check: %v", err)
	}
}

func TestUpdateConfigClearsAndReplacesTheOwnSecret(t *testing.T) {
	e := newEnv(t)
	v, err := e.svc.CreateConfig(e.ctx, domain.NewConfig{ProviderSpecID: e.prov.ID.String(), Name: "mine", APIKey: ptr("sk-1")})
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(v.ID)
	nulls := domain.ConfigPatch{Name: domain.Opt[string]{Set: true}, IsActive: domain.Opt[bool]{Set: true}, IsPublic: domain.Opt[bool]{Set: true}}
	if got, ok, err := e.svc.UpdateConfig(e.ctx, id, nulls); err != nil || !ok || got.Name != "mine" || !got.IsActive {
		t.Fatalf("null name, is_active and is_public leave the config as it was: %+v %v %v", got, ok, err)
	}
	got, ok, err := e.svc.UpdateConfig(e.ctx, id, domain.ConfigPatch{APIKey: domain.Opt[string]{Set: true}})
	if err != nil || !ok || got.APIKey != nil || got.APIKeySecretID != nil {
		t.Fatalf("cleared: %+v %v %v", got, ok, err)
	}
	if _, err := (fakeManager{e.sec, e.ws.ID()}).Get(context.Background(), domain.OwnSecretName(v.ID)); !errors.Is(err, errNotFoundSecret()) {
		t.Fatalf("own secret still there: %v", err)
	}
	if refs, ok := e.sec.refs[v.ID]; !ok || len(refs) != 0 {
		t.Fatalf("refs %+v", refs)
	}
	if _, ok, _ := e.svc.UpdateConfig(e.otherCx, id, domain.ConfigPatch{}); ok {
		t.Fatal("another workspace updated the config")
	}
}

func errNotFoundSecret() error {
	_, err := fakeManager{&fakeSecrets{}, ""}.Get(context.Background(), "")
	return err
}

func TestPlatformConfigsAreReadOnly(t *testing.T) {
	e := newEnv(t)
	c := e.config(PlatformWorkspaceID, "", ptr(domain.ManagedByPlatform))
	id := uuid.MustParse(c.ID)
	var pm *PlatformManagedError
	if _, _, err := e.svc.UpdateConfig(e.ctx, id, domain.ConfigPatch{}); !errors.As(err, &pm) || pm.Verb != "modified" {
		t.Fatalf("update: %v", err)
	}
	if _, err := e.svc.DeleteConfig(e.ctx, id); !errors.As(err, &pm) || pm.Verb != "deleted" {
		t.Fatalf("delete: %v", err)
	}
	var he *HTTPError
	if _, err := e.svc.TestModel(e.ctx, id, e.chat.ID, nil); !errors.As(err, &he) || he.Status != 403 {
		t.Fatalf("test: %v", err)
	}
	if _, err := e.svc.DiscoverConfig(e.ctx, id); !errors.As(err, &he) || he.Status != 403 {
		t.Fatalf("discover: %v", err)
	}
	if v, ok, _ := e.svc.Config(e.otherCx, id); !ok || v.ID != c.ID {
		t.Fatal("the platform config is not visible to a tenant")
	}
}

func TestCallStreamsAccumulatesAndBills(t *testing.T) {
	e := newEnv(t)
	var seen http.Request
	srv := httptest.NewServer(openAIReplay(&seen))
	defer srv.Close()
	c := e.config(e.ws.ID(), srv.URL, nil)
	inst := e.instance(e.ws.ID(), c, e.chat.ID)
	p := api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}
	m, err := e.svc.Model(context.Background(), p, inst)
	if err != nil {
		t.Fatal(err)
	}
	if m.ContextWindow != 1000 || m.ProviderType != "openai" || m.ProviderDisplayName != e.prov.Name || m.ProviderDisplayName == "" || m.APIKeySecret != *c.APIKey || m.EndpointURL != srv.URL {
		t.Fatalf("resolved %+v", m)
	}
	var chunks []api.Chunk
	reply, err := e.svc.Call(context.Background(), p, api.Call{Model: m, Messages: []api.Message{{Role: "user", Content: "hi"}},
		MaxTokens: 100, OnChunk: func(c api.Chunk) { chunks = append(chunks, c) }})
	if err != nil {
		t.Fatal(err)
	}
	if got := seen.Header.Get("Authorization"); got != "Bearer sk-secret-"+e.ws.ID()[:4] {
		t.Fatalf("authorization %q", got)
	}
	if seen.URL.Path != "/v1/chat/completions" {
		t.Fatalf("path %s", seen.URL.Path)
	}
	if reply.Content != "Hello" || reply.Thinking != "think" || reply.FinishReason != "tool_calls" || reply.Interrupted {
		t.Fatalf("reply %+v", reply)
	}
	if len(reply.ToolCalls) != 1 || reply.ToolCalls[0].Name != "f" || reply.ToolCalls[0].Arguments != `{"a":1}` {
		t.Fatalf("tool calls %+v", reply.ToolCalls)
	}
	if reply.Usage.Total != 15 || reply.ProviderCostUSD.String() != "0.0025" || reply.ChunkCount != 3 {
		t.Fatalf("usage %+v cost %s chunks %d", reply.Usage, reply.ProviderCostUSD, reply.ChunkCount)
	}
	want := []api.Chunk{{Delta: "think", Thinking: true, Index: 0}, {Delta: "Hel", Index: 1}, {Delta: "lo", Index: 2}}
	if fmt.Sprint(chunks) != fmt.Sprint(want) {
		t.Fatalf("chunks %+v", chunks)
	}
}

func TestCallWithoutPositiveCostReportsFloatZero(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		sse(w, `{"choices":[{"delta":{"content":"x"}}]}`, `{"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`, `[DONE]`)
	}))
	defer srv.Close()
	p, _ := domain.NewProfile(domain.Profile{Transport: domain.TransportOpenAI, Auth: domain.AuthBearer, ListShape: domain.ListDataID, ReasoningParam: domain.ReasoningEffortParam})
	reply, err := Complete(context.Background(), modelAt(srv.URL, p), requestOf("hi"), nil)
	if err != nil || reply.ProviderCostUSD.String() != "0.0" || reply.Usage.Total != 2 {
		t.Fatalf("%+v %v", reply, err)
	}
}

func TestCallCancelledAfterUsageIsInterrupted(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sse(w, `{"choices":[{"delta":{"content":"part"}}]}`, `{"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}`)
		select {
		case <-r.Context().Done():
		case <-release:
		}
	}))
	defer srv.Close()
	defer close(release)
	p, _ := domain.NewProfile(domain.Profile{Transport: domain.TransportOpenAI, Auth: domain.AuthBearer, ListShape: domain.ListDataID, ReasoningParam: domain.ReasoningEffortParam})
	ctx, cancel := context.WithCancel(context.Background())
	go func() { time.Sleep(300 * time.Millisecond); cancel() }()
	reply, err := Complete(ctx, modelAt(srv.URL, p), requestOf("hi"), nil)
	if err != nil || !reply.Interrupted || reply.Usage.Total != 5 || reply.Content != "part" {
		t.Fatalf("%+v %v", reply, err)
	}
}

func TestCallRefusesAnUnfundedPlatformCall(t *testing.T) {
	e := newEnv(t)
	m := api.ResolvedModel{ModelID: "m", ModelName: "gpt-x", ProviderType: "openai", ManagedBy: api.ManagedByPlatform,
		APIKeySecret: "platform-key", Provider: api.ProviderProfile{Transport: domain.TransportOpenAI, Auth: domain.AuthBearer, BaseURL: "http://127.0.0.1:9", ReasoningParam: domain.ReasoningEffortParam}}
	_, err := e.svc.Call(context.Background(), api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}, api.Call{Model: m})
	var ae *durable.ApplicationError
	if !errors.As(err, &ae) || ae.Type != "UnfundedPlatformCallError" {
		t.Fatalf("%v", err)
	}
	if len(e.sec.gets) != 0 {
		t.Fatalf("the platform key was read: %v", e.sec.gets)
	}
}

func TestCallReadsThePlatformKeyFromThePlatformWorkspace(t *testing.T) {
	e := newEnv(t)
	var seen http.Request
	srv := httptest.NewServer(openAIReplay(&seen))
	defer srv.Close()
	e.sec.rows = append(e.sec.rows, &secretRow{ws: PlatformWorkspaceID, name: "platform-key", value: "sk-platform", id: "p"})
	m := api.ResolvedModel{ModelID: "m", ModelName: "gpt-x", ProviderType: "openai", ManagedBy: api.ManagedByPlatform, EndpointURL: srv.URL,
		APIKeySecret: "platform-key", Provider: api.ProviderProfile{Transport: domain.TransportOpenAI, Auth: domain.AuthBearer, ReasoningParam: domain.ReasoningEffortParam}}
	if _, err := e.svc.Call(context.Background(), api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}, api.Call{Model: m, Funded: true}); err != nil {
		t.Fatal(err)
	}
	if seen.Header.Get("Authorization") != "Bearer sk-platform" || len(e.sec.gets) != 1 || e.sec.gets[0] != "platform/platform-key" {
		t.Fatalf("auth %q gets %v", seen.Header.Get("Authorization"), e.sec.gets)
	}
}

func TestCallRefusesAnUnsupportedEffort(t *testing.T) {
	e := newEnv(t)
	m := api.ResolvedModel{ModelID: "m", ModelName: "gpt-x", ProviderType: "openai", ReasoningLevels: []string{"low"},
		Provider: api.ProviderProfile{Transport: domain.TransportOpenAI, Auth: domain.AuthBearer, BaseURL: "http://127.0.0.1:9", ReasoningParam: domain.ReasoningEffortParam}}
	_, err := e.svc.Call(context.Background(), api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}, api.Call{Model: m, ReasoningEffort: "high"})
	var ae *durable.ApplicationError
	if !errors.As(err, &ae) || ae.Type != "ReasoningSettingError" || !ae.NonRetryable {
		t.Fatalf("%v", err)
	}
}

func TestModelResolution(t *testing.T) {
	e := newEnv(t)
	p := api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}
	if _, err := e.svc.Model(context.Background(), p, uuid.NewString()); !errors.Is(err, api.ErrNotFound) {
		t.Fatalf("missing: %v", err)
	}
	foreignCfg := e.config(e.other.ID(), "", nil)
	inst := e.instance(e.ws.ID(), foreignCfg, e.chat.ID)
	if _, err := e.svc.Model(context.Background(), p, inst); !errors.Is(err, api.ErrRefused) || !strings.Contains(err.Error(), "provider_config from another workspace") {
		t.Fatalf("foreign config: %v", err)
	}
	noWindow := catalogapi.ModelSpec{ID: uuid.New(), ProviderSpecID: e.prov.ID, WorkspaceID: e.ws.ID(), ModelName: "x", Kind: "chat"}
	e.cat.models[noWindow.ID] = noWindow
	own := e.config(e.ws.ID(), "", nil)
	inst = e.instance(e.ws.ID(), own, noWindow.ID)
	if _, err := e.svc.Model(context.Background(), p, inst); !errors.Is(err, api.ErrRefused) || !strings.Contains(err.Error(), "no valid context_window") {
		t.Fatalf("no window: %v", err)
	}
	foreignSpec := catalogapi.ModelSpec{ID: uuid.New(), ProviderSpecID: e.prov.ID, WorkspaceID: e.other.ID(), ModelName: "y", Kind: "chat", ContextWindow: ptr(10)}
	e.cat.models[foreignSpec.ID] = foreignSpec
	inst = e.instance(e.ws.ID(), own, foreignSpec.ID)
	if _, err := e.svc.Model(context.Background(), p, inst); !errors.Is(err, api.ErrRefused) || !strings.Contains(err.Error(), "model_spec") {
		t.Fatalf("foreign spec: %v", err)
	}
	inst = e.instance(e.ws.ID(), own, e.chat.ID)
	in := e.st.instances[inst]
	in.IsActive = false
	e.st.instances[inst] = in
	if _, err := e.svc.Model(context.Background(), p, inst); !errors.Is(err, api.ErrRefused) || !strings.Contains(err.Error(), "is inactive") {
		t.Fatalf("inactive instance: %v", err)
	}
	off := e.config(e.ws.ID(), "", nil)
	off.IsActive = false
	e.st.configs[off.ID] = off
	inst = e.instance(e.ws.ID(), off, e.chat.ID)
	if _, err := e.svc.Model(context.Background(), p, inst); !errors.Is(err, api.ErrRefused) || !strings.Contains(err.Error(), "Provider configuration "+off.ID) {
		t.Fatalf("inactive configuration: %v", err)
	}
}

func TestTestModelNeverEchoesTheProviderBody(t *testing.T) {
	e := newEnv(t)
	cases := []struct {
		status          int
		body, msg, kind string
	}{
		{401, `{"error":{"message":"invalid api_key sk-LEAKED"}}`, "Authentication failed - please check your API key", "AuthenticationError"},
		{401, `{"error":{"message":"Incorrect API key provided: sk-LEAKED"}}`, "Test failed: the provider answered with HTTP 401", "LLMProviderHTTPError"},
		{429, `{"error":{"message":"slow down sk-LEAKED"}}`, "Test failed: the provider answered with HTTP 429", "LLMProviderHTTPError"},
		{500, `{"error":{"message":"boom sk-LEAKED"}}`, "Test failed: the provider answered with HTTP 500", "LLMProviderHTTPError"},
	}
	for _, c := range cases {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(c.status)
			_, _ = w.Write([]byte(c.body))
		}))
		cfg := e.config(e.ws.ID(), srv.URL, nil)
		r, err := e.svc.TestModel(e.ctx, uuid.MustParse(cfg.ID), e.chat.ID, ptr("hello"))
		srv.Close()
		if err != nil {
			t.Fatal(err)
		}
		if r.Success || r.Message != c.msg || r.ErrorType == nil {
			t.Errorf("%d: %+v (%s)", c.status, r, str(r.ErrorType))
		}
		if strings.Contains(fmt.Sprintf("%+v %s %s", r, str(r.ErrorType), str(r.ResponseContent)), "LEAKED") {
			t.Errorf("%d: the provider body reached the response", c.status)
		}
	}
}

func TestTestModelSucceedsUnpriced(t *testing.T) {
	e := newEnv(t)
	var seen http.Request
	srv := httptest.NewServer(openAIReplay(&seen))
	defer srv.Close()
	cfg := e.config(e.ws.ID(), srv.URL, nil)
	r, err := e.svc.TestModel(e.ctx, uuid.MustParse(cfg.ID), e.chat.ID, nil)
	if err != nil || !r.Success || r.Message != "LLM test successful" || str(r.ResponseContent) != "Hello" || *r.TokensUsed != 15 || r.Cost.String() != "0.0025" {
		t.Fatalf("%+v %v", r, err)
	}
	var he *HTTPError
	if _, err := e.svc.TestModel(e.ctx, uuid.New(), e.chat.ID, nil); !errors.As(err, &he) || he.Detail != "Provider config not found" {
		t.Fatalf("missing config: %v", err)
	}
	if _, err := e.svc.TestModel(e.ctx, uuid.MustParse(cfg.ID), uuid.New(), nil); !errors.As(err, &he) || he.Detail != "Model spec not found" {
		t.Fatalf("missing spec: %v", err)
	}
	embed := catalogapi.ModelSpec{ID: uuid.New(), WorkspaceID: PlatformWorkspaceID, ModelName: "emb", Kind: "embedding"}
	e.cat.models[embed.ID] = embed
	r, err = e.svc.TestModel(e.ctx, uuid.MustParse(cfg.ID), embed.ID, nil)
	if err != nil || r.Success || str(r.ErrorType) != "UnsupportedModelKind" || r.Message != "A embedding model cannot be tested with a chat message" {
		t.Fatalf("embedding: %+v %v", r, err)
	}
}

func TestDiscoveryPartitionsAndUpserts(t *testing.T) {
	e := newEnv(t)
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		if r.URL.Path != "/v1/models" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(`{"data":[
			{"id":"good","name":"Good","context_length":8000,"pricing":{"prompt":"0.000001","completion":"0.000002"},"architecture":{"input_modalities":["text","image"],"output_modalities":["text"]}},
			{"id":"nowindow"},
			{"id":"audio","context_length":10,"architecture":{"output_modalities":["audio"]}},
			{"id":"emb","context_length":512,"architecture":{"output_modalities":["embeddings"]}},
			{"id":""}
		]}`))
	}))
	defer srv.Close()
	cfg := e.config(e.ws.ID(), srv.URL, nil)
	d, err := e.svc.DiscoverConfig(e.ctx, uuid.MustParse(cfg.ID))
	if err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer sk-secret-"+e.ws.ID()[:4] {
		t.Fatalf("auth %q", auth)
	}
	if len(d.Models) != 2 || d.Models[0].ModelName != "good" || d.Models[1].Kind != "embedding" || d.New != 1 {
		t.Fatalf("models %+v", d)
	}
	good := e.cat.upserted[0]
	if good.DisplayName != "Good" || *good.ContextWindow != 8000 || good.InputCostPerToken.String() != "0.000001" || !good.SupportsVision || good.Description != nil {
		t.Fatalf("upserted %+v", good)
	}
	want := fmt.Sprint([]Skipped{{"nowindow", []string{"context_window"}}, {"audio", []string{"kind"}}})
	if fmt.Sprint(d.Skipped) != want {
		t.Fatalf("skipped %v", d.Skipped)
	}

	var he *HTTPError
	empty := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(401) }))
	defer empty.Close()
	cfg = e.config(e.ws.ID(), empty.URL, nil)
	if _, err := e.svc.DiscoverConfig(e.ctx, uuid.MustParse(cfg.ID)); !errors.As(err, &he) || he.Status != 400 ||
		he.Detail != "No models discovered for provider 'openai'. The provider may not support model listing or the API key may be invalid." {
		t.Fatalf("nothing: %v", err)
	}
	if _, err := e.svc.DiscoverPreview(e.ctx, "nope", nil, nil); !errors.As(err, &he) || he.Status != 404 || he.Detail != "Provider 'nope' not found" {
		t.Fatalf("preview: %v", err)
	}
}

func TestInstances(t *testing.T) {
	e := newEnv(t)
	cfg := e.config(e.ws.ID(), "", nil)
	v, err := e.svc.CreateInstance(e.ctx, domain.NewInstance{ProviderConfigID: cfg.ID, ModelSpecID: e.chat.ID.String(), Name: "mine"})
	if err != nil {
		t.Fatal(err)
	}
	if v.Model == nil || v.Model.Kind != "chat" || v.Provider == nil || str(v.IconURL) != "http://api.test/static/icons/providers/openai.svg" {
		t.Fatalf("view %+v", v)
	}
	var nf *NotFoundError
	if _, err := e.svc.CreateInstance(e.otherCx, domain.NewInstance{ProviderConfigID: cfg.ID, ModelSpecID: e.chat.ID.String()}); !errors.As(err, &nf) ||
		nf.Detail != "Provider config "+cfg.ID+" not found" {
		t.Fatalf("foreign config: %v", err)
	}
	ok, failed, err := e.svc.CreateInstances(e.ctx, []domain.NewInstance{
		{ProviderConfigID: cfg.ID, ModelSpecID: e.chat.ID.String(), Name: "b"},
		{ProviderConfigID: cfg.ID, ModelSpecID: uuid.Nil.String(), Name: "c"},
	})
	if err != nil || len(ok) != 1 || len(failed) != 1 || failed[0].Index != 1 || failed[0].Error != "Model spec "+uuid.Nil.String()+" not found" {
		t.Fatalf("bulk %v %+v %v", len(ok), failed, err)
	}
	for kind, n := range map[string]int{"chat": 2, "embedding": 0} {
		list, err := e.svc.Instances(e.ctx, InstanceFilter{Kind: ptr(kind)})
		if err != nil || len(list) != n {
			t.Errorf("kind %s: %d %v", kind, len(list), err)
		}
	}
	if deleted, _ := e.svc.DeleteInstance(e.otherCx, uuid.MustParse(v.ID)); deleted {
		t.Fatal("another workspace deleted the instance")
	}
	if deleted, err := e.svc.DeleteInstance(e.ctx, uuid.MustParse(v.ID)); !deleted || err != nil {
		t.Fatalf("delete: %v", err)
	}
}

func TestCurrencyDefaultsToUSD(t *testing.T) {
	e := newEnv(t)
	if e.svc.Currency() != (money.USDAtProviderCost{}).Currency() {
		t.Fatal(e.svc.Currency())
	}
}

func modelAt(endpoint string, p domain.Profile) transport.Model {
	return transport.Model{ProviderType: "openai", ModelName: "m", APIKey: "k", EndpointURL: endpoint, Profile: p, Transport: http.DefaultTransport}
}

func requestOf(text string) transport.Request {
	return transport.Request{Messages: []api.Message{{Role: "user", Content: text}}, MaxTokens: 10}
}

func TestAPlatformConfigTakesOnlyThePlatformSpecsOfItsProvider(t *testing.T) {
	e := newEnv(t)
	plat := e.config(PlatformWorkspaceID, "", ptr(domain.ManagedByPlatform))
	cw := 1000
	own := catalogapi.ModelSpec{ID: uuid.New(), ProviderSpecID: e.prov.ID, WorkspaceID: e.ws.ID(), ModelName: "free", Kind: "chat", ContextWindow: &cw}
	otherProv := catalogapi.ProviderSpec{ID: uuid.New(), ProviderKey: "other", ProviderType: "openai", Name: "Other", Transport: domain.TransportOpenAI}
	e.cat.providers[otherProv.ID] = otherProv
	elsewhere := catalogapi.ModelSpec{ID: uuid.New(), ProviderSpecID: otherProv.ID, WorkspaceID: PlatformWorkspaceID, ModelName: "o", Kind: "chat", ContextWindow: &cw}
	e.cat.models[own.ID], e.cat.models[elsewhere.ID] = own, elsewhere

	for _, spec := range []uuid.UUID{own.ID, elsewhere.ID} {
		_, err := e.svc.CreateInstance(e.ctx, domain.NewInstance{ProviderConfigID: plat.ID, ModelSpecID: spec.String(), Name: "x"})
		var br *BadRequestError
		if !errors.As(err, &br) || !strings.Contains(br.Detail, "platform-supplied") {
			t.Fatalf("spec %s on the platform config: %v", spec, err)
		}
	}
	if _, err := e.svc.CreateInstance(e.ctx, domain.NewInstance{ProviderConfigID: plat.ID, ModelSpecID: e.chat.ID.String(), Name: "ok"}); err != nil {
		t.Fatalf("the platform's own spec: %v", err)
	}
	ok, failed, err := e.svc.CreateInstances(e.ctx, []domain.NewInstance{{ProviderConfigID: plat.ID, ModelSpecID: own.ID.String(), Name: "x"}})
	if err != nil || len(ok) != 0 || len(failed) != 1 || !strings.Contains(failed[0].Error, "platform-supplied") {
		t.Fatalf("bulk: %v %v %v", ok, failed, err)
	}

	p := api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}
	for _, spec := range []uuid.UUID{own.ID, elsewhere.ID} {
		inst := e.instance(e.ws.ID(), plat, spec)
		if _, err := e.svc.Model(context.Background(), p, inst); !errors.Is(err, api.ErrRefused) || !strings.Contains(err.Error(), "platform-supplied") {
			t.Fatalf("an existing instance of spec %s on the platform config: %v", spec, err)
		}
	}
	if _, err := e.svc.Model(context.Background(), p, e.instance(e.ws.ID(), plat, e.chat.ID)); err != nil {
		t.Fatalf("the platform's own spec: %v", err)
	}
}

func TestTheTestRouteCutsAnEndlessAnswer(t *testing.T) {
	e := newEnv(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		for r.Context().Err() == nil {
			if _, err := fmt.Fprint(w, "data: {\"choices\":[{\"delta\":{\"content\":\"aaaaaaaaaaaaaaaa\"}}]}\n\n"); err != nil {
				return
			}
			w.(http.Flusher).Flush()
		}
	}))
	defer srv.Close()
	cfg := e.config(e.ws.ID(), srv.URL, nil)
	r, err := e.svc.TestModel(e.ctx, uuid.MustParse(cfg.ID), e.chat.ID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if r.Success || str(r.ErrorType) != "ResponseTooLarge" || r.ResponseContent != nil {
		t.Fatalf("%+v (%s)", r, str(r.ErrorType))
	}
}

func TestDiscoveryRefusesAnOversizedListing(t *testing.T) {
	e := newEnv(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = fmt.Fprint(w, `{"data":[`)
		row := `{"id":"m","context_length":8000},`
		for range (9 << 20) / len(row) {
			_, _ = fmt.Fprint(w, row)
		}
		_, _ = fmt.Fprint(w, `{"id":"last","context_length":8000}]}`)
	}))
	defer srv.Close()
	cfg := e.config(e.ws.ID(), srv.URL, nil)
	var he *HTTPError
	if _, err := e.svc.DiscoverConfig(e.ctx, uuid.MustParse(cfg.ID)); !errors.As(err, &he) || he.Status != 400 {
		t.Fatalf("a 9 MiB listing: %v", err)
	}
}

type rubPricing struct{}

func (rubPricing) Currency() money.Currency { return "RUB" }

func TestCurrencyComesFromTheExtension(t *testing.T) {
	svc := New(Deps{Pricing: func() money.CustomerPricing { return rubPricing{} }})
	if svc.Currency() != "RUB" {
		t.Fatal(svc.Currency())
	}
}
