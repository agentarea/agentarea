//go:build suite

// Package catalog pins the registries routes
// (.omc/research/go-migration/dossiers/catalog.md).
package catalog

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

const missing = "00000000-0000-4000-8000-000000000000"

func TestAWorkspaceMayNotWriteThePlatformCatalog(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/registries/"), map[string]any{
		"name": "mine", "registry_type": "skills", "source_type": "managed",
	}).Expect(http.StatusForbidden).Match(h.Problem(http.StatusForbidden, "http_error",
		"Only the platform may modify the global registry catalog"))
	w.Owner.Delete(t, w.Path("/registries/"+missing)).Expect(http.StatusForbidden)
}

func TestMissingRegistryIs404(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Get(t, w.Path("/registries/"+missing)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Registry not found"))
	w.Owner.Get(t, w.Path("/workspace-registries/"+missing)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Registry not found"))
	w.Owner.Get(t, w.Path("/registries/"+missing+"/items")).Expect(http.StatusNotFound)
}

func TestANewWorkspaceHasNoRegistriesOfItsOwn(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Get(t, w.Path("/workspace-registries")).Expect(http.StatusOK).Match([]any{})
	w.Owner.Get(t, w.Path("/registries/?scope=workspace")).Expect(http.StatusOK).Match([]any{})
}

func TestQueryValidation(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Get(t, w.Path("/registries/?scope=team")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/registries/catalog/search?limit=0")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/registries/catalog/search?q=zzzz-no-such-entry")).Expect(http.StatusOK).Match([]any{})
}

func TestUnknownProviderAndModelSpecsAre404(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Member.Get(t, w.Path("/provider-specs/"+missing)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Provider specification not found"))
	w.Member.Get(t, w.Path("/provider-specs/by-key/no-such-provider")).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Provider specification not found"))
	w.Member.Get(t, w.Path("/model-specs/"+missing)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Model specification not found"))
	w.Member.Get(t, w.Path("/model-specs/by-provider/"+missing+"/gpt")).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Model specification 'gpt' not found for provider"))
	w.Member.Get(t, w.Path("/model-specs/by-provider/"+missing)).Expect(http.StatusOK)
	w.Owner.Delete(t, w.Path("/model-specs/"+missing)).Expect(http.StatusNotFound)
	w.Owner.Patch(t, w.Path("/model-specs/"+missing), map[string]any{}).Expect(http.StatusNotFound)
}

func TestProviderSpecListsAnswer(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Member.Get(t, w.Path("/provider-specs/")).Expect(http.StatusOK).Array()
	w.Member.Get(t, w.Path("/provider-specs/with-models?is_builtin=true")).Expect(http.StatusOK).Array()
	w.Member.Get(t, w.Path("/provider-specs/?is_builtin=maybe")).Expect(http.StatusUnprocessableEntity)
	w.Member.Get(t, w.Path("/model-specs/?kind=audio")).Expect(http.StatusUnprocessableEntity)
	w.Member.Get(t, w.Path("/model-specs/?provider_spec_id="+missing)).Expect(http.StatusOK).Match([]any{})
}

func TestModelSpecWritesAreForAdmins(t *testing.T) {
	w := h.NewWorkspace(t)
	body := map[string]any{"provider_spec_id": missing, "model_name": "m", "display_name": "M", "context_window": 1000}
	w.Member.Post(t, w.Path("/model-specs/"), body).Expect(http.StatusForbidden).
		Match(h.Problem(http.StatusForbidden, "http_error", "Only a workspace admin may perform this action"))
	w.Member.Post(t, w.Path("/model-specs/upsert"), body).Expect(http.StatusForbidden)
	w.Member.Delete(t, w.Path("/model-specs/"+missing)).Expect(http.StatusForbidden)
}

func TestModelSpecOnAnUnknownProviderIs404(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/model-specs/"), map[string]any{
		"provider_spec_id": missing, "model_name": "m", "display_name": "M", "context_window": 1000,
	}).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Provider specification not found"))
	w.Owner.Post(t, w.Path("/model-specs/upsert"), map[string]any{
		"provider_spec_id": missing, "model_name": "m", "display_name": "M", "context_window": 1000,
	}).Expect(http.StatusNotFound)
	w.Owner.Post(t, w.Path("/model-specs/"), map[string]any{
		"provider_spec_id": missing, "model_name": "m", "display_name": "M",
	}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/model-specs/"), map[string]any{
		"provider_spec_id": missing, "model_name": "m", "display_name": "M", "context_window": 1, "input_cost_per_token": true,
	}).Expect(http.StatusUnprocessableEntity)
}

func TestItemUpdatesArePlatformWrites(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/registries/catalog/items/"+missing+"/update"), nil).Expect(http.StatusForbidden).
		Match(h.Problem(http.StatusForbidden, "http_error", "Only the platform may modify the global registry catalog"))
	w.Owner.Post(t, w.Path("/registries/"+missing+"/update-all"), nil).Expect(http.StatusForbidden)
}

func TestWorkspaceRegistryLifecycle(t *testing.T) {
	w := h.NewWorkspace(t)
	create := map[string]any{"name": "team-skills", "source_type": "github", "source_url": "acme/skills"}
	w.Member.Post(t, w.Path("/workspace-registries"), create).Expect(http.StatusForbidden)
	w.Owner.Post(t, w.Path("/workspace-registries"), map[string]any{
		"name": "x", "source_type": "github", "source_url": "acme/skills", "scope": "platform",
	}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/workspace-registries"), map[string]any{
		"name": "x", "source_type": "github", "source_url": "acme/skills", "credentials_secret_id": missing,
	}).Expect(http.StatusNotFound)
	reg := w.Owner.Post(t, w.Path("/workspace-registries"), create).Expect(http.StatusCreated).Object()
	if reg["scope"] != "workspace" || reg["trust"] != "private" || reg["registry_type"] != "skills" || reg["mode"] != "mirror" {
		t.Fatalf("created = %v", reg)
	}
	id := reg["id"].(string)
	w.Owner.Post(t, w.Path("/workspace-registries"), create).Expect(http.StatusConflict).
		Match(h.Problem(http.StatusConflict, "http_error", "This workspace already has a registry named 'team-skills'"))
	w.Owner.Patch(t, w.Path("/workspace-registries/"+id), map[string]any{}).Expect(http.StatusBadRequest).
		Match(h.Problem(http.StatusBadRequest, "http_error", "No fields to update"))
	w.Owner.Patch(t, w.Path("/workspace-registries/"+id), map[string]any{"description": "d", "trust": "community"}).
		Expect(http.StatusOK)
	w.Member.Get(t, w.Path("/workspace-registries/"+id)).Expect(http.StatusOK)
	w.Member.Patch(t, w.Path("/workspace-registries/"+id), map[string]any{"description": "e"}).Expect(http.StatusForbidden)
	w.Owner.Patch(t, w.Path("/workspace-registries/"+missing), map[string]any{"description": "e"}).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Registry not found"))
}

func TestSyncAndRemoveNeedTheRightCaller(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/registries/"+missing+"/sync"), nil).Expect(http.StatusForbidden)
	w.Member.Post(t, w.Path("/workspace-registries/"+missing+"/sync"), nil).Expect(http.StatusForbidden).
		Match(h.Problem(http.StatusForbidden, "http_error", "Only a workspace admin may perform this action"))
	w.Member.Delete(t, w.Path("/workspace-registries/"+missing)).Expect(http.StatusForbidden)
	w.Owner.Post(t, w.Path("/workspace-registries/"+missing+"/sync"), nil).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Registry not found"))
	w.Owner.Delete(t, w.Path("/workspace-registries/"+missing)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Registry not found"))
}

func TestBrowseShowsConnectionsAndPrices(t *testing.T) {
	w := h.NewWorkspace(t)
	page := w.Owner.Get(t, w.Path("/registries/catalog/browse?registry_type=mcp_servers&q=suite%20paid")).Expect(http.StatusOK).Object()
	items, _ := page["items"].([]any)
	if len(items) != 1 {
		t.Fatalf("browse %v", page)
	}
	item := items[0].(map[string]any)
	if conns, ok := item["workspace_connections"].([]any); !ok || len(conns) != 0 {
		t.Fatalf("workspace_connections %v", item["workspace_connections"])
	}
	pricing, _ := item["pricing"].(map[string]any)
	from, _ := pricing["price_from"].(map[string]any)
	if pricing["kind"] != "paid" || from["amount"] != "0.02" || from["basis"] != "vendor_cost" || from["currency"] != "USD" {
		t.Fatalf("pricing %v", item["pricing"])
	}
	got := w.Owner.Get(t, w.Path("/registries/catalog/items/5e1f0000-0000-4000-8000-000000000113")).Expect(http.StatusOK).Object()
	if got["name"] != "Suite Paid" || got["pricing"] == nil {
		t.Fatalf("item %v", got)
	}
	w.Owner.Get(t, w.Path("/registries/catalog/items/5e1f0000-0000-4000-8000-0000000009ff")).Expect(http.StatusNotFound)
}
