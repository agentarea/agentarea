//go:build suite

// Package models pins provider configurations, model instances and pricing
// (.omc/research/go-migration/dossiers/models.md). It needs seed.sql, which `stack.sh up` applies:
// the stack runs no catalog reconcile, so no provider spec exists otherwise.
package models

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

const (
	providerSpec = "5e1f0000-0000-4000-8000-000000000001"
	chatSpec     = "5e1f0000-0000-4000-8000-000000000002"
	embedSpec    = "5e1f0000-0000-4000-8000-000000000003"
	notAdmin     = "Only a workspace admin may perform this action"
)

func config(w *h.Workspace, id any, name string, endpoint any, instances any) map[string]any {
	return map[string]any{
		"id": id, "provider_spec_id": providerSpec, "name": name, "endpoint_url": endpoint,
		"workspace_id": w.ID, "created_by": w.People.Owner.ID, "is_active": true, "is_public": false,
		"created_at": h.AnyTimestamp, "updated_at": h.AnyTimestamp, "managed_by": nil, "requires_api_key": true,
		"provider_spec_name": "Suite OpenAI", "provider_spec_key": "suite-openai", "model_instance_ids": instances,
	}
}

func instance(id, configID any, spec, name, kind string, model string) map[string]any {
	return map[string]any{
		"id": id, "provider_config_id": configID, "model_spec_id": spec, "name": name, "description": nil,
		"is_active": true, "is_public": false, "created_at": h.AnyTimestamp, "updated_at": h.AnyTimestamp,
		"provider_name": "Suite OpenAI", "provider_key": "suite-openai", "provider_icon_url": h.Pattern(`/static/icons/providers/openai\.svg$`),
		"model_name": model, "model_display_name": h.AnyString, "model_kind": kind, "config_name": "Mine",
		"managed_by": nil, "tags": []any{},
	}
}

func createConfig(t *testing.T, w *h.Workspace, body map[string]any) map[string]any {
	t.Helper()
	return w.Owner.Post(t, w.Path("/provider-configs/"), body).Expect(http.StatusOK).Object()
}

// Every caller sees the deployment's one currency; which one it is (USD, or
// the pricing extension's) is the service's unit tests' concern.
func TestPricingCurrency(t *testing.T) {
	w := h.NewWorkspace(t)
	seen := map[any]bool{}
	for _, c := range []*h.Client{w.Owner, w.Member, w.Outsider, w.APIKey(t)} {
		body := c.Get(t, "/v1/pricing/currency").Expect(http.StatusOK).Match(map[string]any{"currency": h.Pattern(`^[A-Z]{3}$`)}).Object()
		seen[body["currency"]] = true
	}
	if len(seen) != 1 {
		t.Fatalf("callers see different currencies: %v", seen)
	}
	w.Anonymous.Get(t, "/v1/pricing/currency").Expect(http.StatusUnauthorized)
}

func TestConfigLifecycleKeepsTheKeyOutOfEveryAnswer(t *testing.T) {
	w := h.NewWorkspace(t)
	resp := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": providerSpec, "name": "  Mine  ", "api_key": "  sk-suite-secret  ",
	}).Expect(http.StatusOK)
	if strings.Contains(string(resp.Body), "sk-suite-secret") {
		t.Fatal("the key is in the create answer")
	}
	created := resp.Match(config(w, h.AnyUUID, "Mine", nil, []any{})).Object()
	id := created["id"].(string)
	path := w.Path("/provider-configs/" + id)

	w.Member.Get(t, path).Expect(http.StatusOK).Match(config(w, id, "Mine", nil, []any{}))
	list := w.Member.Get(t, w.Path("/provider-configs/")).Expect(http.StatusOK)
	if strings.Contains(string(list.Body), "sk-suite-secret") || !strings.Contains(string(list.Body), id) {
		t.Fatalf("member list: %s", list.Body)
	}
	w.APIKey(t).Get(t, w.Path("/provider-configs/")).Expect(http.StatusOK)

	w.Outsider.Get(t, w.OutsiderPath("/provider-configs/"+id)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Provider configuration not found"))
	w.Outsider.Get(t, path).Expect(http.StatusForbidden)

	w.Member.Post(t, w.Path("/provider-configs/"), map[string]any{"provider_spec_id": providerSpec, "name": "x"}).
		Expect(http.StatusForbidden).Match(h.Problem(http.StatusForbidden, "http_error", notAdmin))
	w.Member.Patch(t, path, map[string]any{"name": "theirs"}).Expect(http.StatusForbidden)
	w.Member.Delete(t, path).Expect(http.StatusForbidden)

	w.Owner.Patch(t, path, map[string]any{"name": "Renamed", "is_active": false}).Expect(http.StatusOK).
		Match(func() map[string]any { c := config(w, id, "Renamed", nil, []any{}); c["is_active"] = false; return c }())
	w.Owner.Put(t, path, map[string]any{"api_key": ""}).Expect(http.StatusOK)
	w.Owner.Patch(t, path, map[string]any{"name": nil, "is_active": nil, "is_public": nil}).Expect(http.StatusOK).
		Match(func() map[string]any { c := config(w, id, "Renamed", nil, []any{}); c["is_active"] = false; return c }())

	w.Owner.Delete(t, path).Expect(http.StatusOK).Match(map[string]any{"message": "Provider configuration deleted successfully"})
	w.Owner.Get(t, path).Expect(http.StatusNotFound)
	w.Owner.Delete(t, path).Expect(http.StatusNotFound)
}

func TestConfigValidation(t *testing.T) {
	w := h.NewWorkspace(t)
	for _, body := range []map[string]any{
		{"provider_spec_id": providerSpec, "name": "   "},
		{"provider_spec_id": providerSpec, "name": "x", "color": "red"},
		{"provider_spec_id": providerSpec, "name": "x", "api_key": "k", "api_key_secret_id": providerSpec},
		{"provider_spec_id": providerSpec, "name": "x", "endpoint_url": "https://h/v1?q=1"},
		{"name": "x"},
	} {
		w.Owner.Post(t, w.Path("/provider-configs/"), body).Expect(http.StatusUnprocessableEntity)
	}
	w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{"provider_spec_id": "5e1f0000-0000-4000-8000-0000000000ff", "name": "x"}).
		Expect(http.StatusNotFound).Match(h.Problem(http.StatusNotFound, "not_found", "Provider spec not found"))
	w.Owner.Get(t, w.Path("/provider-configs/admin/a.b/logo")).Expect(http.StatusBadRequest).
		Match(h.Problem(http.StatusBadRequest, "http_error", "Invalid provider key"))
	w.Owner.Get(t, w.Path("/provider-configs/admin/openai%0A/logo")).Expect(http.StatusBadRequest)
}

func TestInstancesAreMemberLevelAndWorkspaceScoped(t *testing.T) {
	w := h.NewWorkspace(t)
	cfg := createConfig(t, w, map[string]any{"provider_spec_id": providerSpec, "name": "Mine", "api_key": "sk-x"})
	cfgID := cfg["id"].(string)

	created := w.Member.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfgID, "model_spec_id": chatSpec, "name": "Chat", "ignored": true,
	}).Expect(http.StatusOK).Match(instance(h.AnyUUID, cfgID, chatSpec, "Chat", "chat", "suite-chat")).Object()
	id := created["id"].(string)

	bulk := w.APIKey(t).Post(t, w.Path("/model-instances/bulk"), map[string]any{"items": []any{
		map[string]any{"provider_config_id": cfgID, "model_spec_id": embedSpec, "name": "Embed"},
		map[string]any{"provider_config_id": cfgID, "model_spec_id": "5e1f0000-0000-4000-8000-0000000000ff", "name": "Missing"},
	}}).Expect(http.StatusOK).Object()
	if fmt.Sprintf("%v %v", bulk["succeeded_count"], bulk["failed_count"]) != "1 1" {
		t.Fatalf("bulk %v", bulk)
	}
	if err := h.Compare(bulk["failed"], []any{map[string]any{"index": 1, "model_spec_id": "5e1f0000-0000-4000-8000-0000000000ff",
		"error": "Model spec 5e1f0000-0000-4000-8000-0000000000ff not found"}}); err != nil {
		t.Fatal(err)
	}

	chats := ownInstances(w.Owner.Get(t, w.Path("/model-instances/?kind=chat")).Expect(http.StatusOK).Array())
	if err := h.Compare(chats, []any{instance(id, cfgID, chatSpec, "Chat", "chat", "suite-chat")}); err != nil {
		t.Fatal(err)
	}
	if videos := ownInstances(w.Owner.Get(t, w.Path("/model-instances/?kind=video")).Expect(http.StatusOK).Array()); len(videos) != 0 {
		t.Fatalf("video instances: %v", videos)
	}
	w.Owner.Get(t, w.Path("/model-instances/?kind=audio")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/provider-configs/"+cfgID)).Expect(http.StatusOK).Match(
		config(w, cfgID, "Mine", nil, h.Unordered(chatSpec, embedSpec)))

	w.Outsider.Get(t, w.OutsiderPath("/model-instances/"+id)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Model instance not found"))
	w.Outsider.Post(t, w.OutsiderPath("/model-instances/"), map[string]any{
		"provider_config_id": cfgID, "model_spec_id": chatSpec, "name": "Stolen",
	}).Expect(http.StatusNotFound).Match(h.Problem(http.StatusNotFound, "not_found", "Provider config "+cfgID+" not found"))
	w.Outsider.Delete(t, w.OutsiderPath("/model-instances/"+id)).Expect(http.StatusNotFound)

	w.Member.Delete(t, w.Path("/model-instances/"+id)).Expect(http.StatusOK).
		Match(map[string]any{"message": "Model instance deleted successfully"})
	w.Member.Get(t, w.Path("/model-instances/"+id)).Expect(http.StatusNotFound)
}

func TestDiscoveryIsAdminOnly(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Member.Post(t, w.Path("/provider-configs/discover-preview"), map[string]any{"provider_key": "suite-openai"}).
		Expect(http.StatusForbidden).Match(h.Problem(http.StatusForbidden, "http_error", notAdmin))
	w.Owner.Post(t, w.Path("/provider-configs/discover-preview"), map[string]any{"provider_key": "nope"}).
		Expect(http.StatusNotFound).Match(h.Problem(http.StatusNotFound, "http_error", "Provider 'nope' not found"))
}

// fakeProvider answers chat completions the way a provider that rejects the key does,
// with a body that must not reach the caller (GHSA-pprc-x767-m6jg).
func fakeProvider(t *testing.T, status int) string {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if status != http.StatusOK {
			w.WriteHeader(status)
			_, _ = w.Write([]byte(`{"error":{"message":"rejected sk-PROVIDER-ECHO"}}`))
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		for _, ev := range []string{
			`{"choices":[{"delta":{"content":"pong"}}]}`,
			`{"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4,"cost":0.0001}}`,
			`[DONE]`,
		} {
			_, _ = fmt.Fprintf(w, "data: %s\n\n", ev)
		}
	}))
	t.Cleanup(srv.Close)
	return h.StackURL(srv.URL)
}

func TestTestRouteNeverEchoesTheProvider(t *testing.T) {
	w := h.NewWorkspace(t)
	resp := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": providerSpec, "name": "Mine", "api_key": "sk-x", "endpoint_url": fakeProvider(t, http.StatusUnauthorized),
	})
	if resp.Status == http.StatusBadRequest {
		resp.Match(h.Problem(http.StatusBadRequest, "bad_request", "endpoint_url must be a public address this deployment may call"))
		t.Skip("this deployment refuses private endpoints (AGENTAREA_HTTP_ALLOW_PRIVATE unset); the refusal is pinned")
	}
	cfgID := resp.Expect(http.StatusOK).Object()["id"].(string)
	body := w.Member.Post(t, w.Path("/model-instances/test"), map[string]any{
		"provider_config_id": cfgID, "model_spec_id": chatSpec,
	}).Expect(http.StatusOK)
	if strings.Contains(string(body.Body), "PROVIDER-ECHO") {
		t.Fatalf("the provider body reached the answer: %s", body.Body)
	}
	body.Match(map[string]any{
		"success": false, "message": "Test failed: the provider answered with HTTP 401", "response_content": nil,
		"error_type": "LLMProviderHTTPError", "provider_type": "openai", "model_name": "suite-chat", "cost": nil,
		"currency": "USD", "tokens_used": nil,
	})

	ok := createConfig(t, w, map[string]any{
		"provider_spec_id": providerSpec, "name": "Good", "api_key": "sk-y", "endpoint_url": fakeProvider(t, http.StatusOK),
	})
	w.Member.Post(t, w.Path("/model-instances/test"), map[string]any{
		"provider_config_id": ok["id"], "model_spec_id": chatSpec, "test_message": "ping",
	}).Expect(http.StatusOK).Match(map[string]any{
		"success": true, "message": "LLM test successful", "response_content": "pong", "error_type": nil,
		"provider_type": "openai", "model_name": "suite-chat", "cost": "0.0001", "currency": "USD", "tokens_used": 4,
	})
	w.Member.Post(t, w.Path("/model-instances/test"), map[string]any{
		"provider_config_id": ok["id"], "model_spec_id": embedSpec,
	}).Expect(http.StatusOK).Match(map[string]any{
		"success": false, "message": "A embedding model cannot be tested with a chat message", "response_content": nil,
		"error_type": "UnsupportedModelKind", "provider_type": nil, "model_name": "suite-embed", "cost": nil,
		"currency": "USD", "tokens_used": nil,
	})
}

// ownInstances drops the platform's instances, which every workspace lists.
func ownInstances(all []any) []any {
	out := []any{}
	for _, v := range all {
		if v.(map[string]any)["managed_by"] != "platform" {
			out = append(out, v)
		}
	}
	return out
}
