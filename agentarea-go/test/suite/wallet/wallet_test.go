//go:build suite

// Package wallet pins /v1/workspaces/{workspace}/agents/{agent_id}/wallet
// (.omc/research/go-migration/dossiers/wallet.md, section 2).
package wallet

import (
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

func newAgent(t *testing.T, w *h.Workspace) string {
	t.Helper()
	return w.Owner.Post(t, w.Path("/agents/"), map[string]any{"name": "Payer", "instruction": "pay", "tools": []any{}}).Expect(http.StatusOK).Object()["id"].(string)
}

var createBody = map[string]any{
	"wallet_type": "x402", "x402_config": map[string]any{},
	"credentials":        map[string]any{"x402_private_key": "0xSUITESECRET"},
	"service_budget_usd": 5, "service_budget_period": "daily",
}

func TestWalletLifecycleAndKeysNeverReturn(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := newAgent(t, w)
	path := w.Path("/agents/" + agent + "/wallet")

	w.Owner.Get(t, path).Expect(http.StatusNotFound)
	created := w.Owner.Post(t, path, createBody).Expect(http.StatusCreated)
	if strings.Contains(string(created.Body), "SUITESECRET") {
		t.Fatal("a key came back")
	}
	obj := created.Match(map[string]any{
		"id": h.AnyUUID, "agent_id": agent, "wallet_type": "x402",
		"x402_config": map[string]any{"network": "eip155:8453", "facilitator_url": "https://x402.org/facilitator", "scheme": "exact", "signer_type": "evm"},
		"mpp_config":  nil, "has_credentials": true, "service_budget_usd": "5.000000", "service_budget_period": "daily",
		"status": "active", "created_at": h.AnyTimestamp, "updated_at": h.AnyTimestamp,
	}).Object()
	w.Owner.Post(t, path, createBody).Expect(http.StatusConflict)

	w.Owner.Post(t, path+"/fund", map[string]any{"service_budget_usd": "7.5"}).Expect(http.StatusOK).Object()
	w.Owner.Get(t, path+"/balance").Expect(http.StatusOK).Match(map[string]any{
		"service_budget_usd": "7.500000", "service_budget_period": "daily", "total_spent_current_period": "0", "remaining": "7.500000",
	})
	w.Owner.Put(t, path, map[string]any{"status": "disabled"}).Expect(http.StatusOK)
	w.Owner.Get(t, path+"/payments").Expect(http.StatusOK).Match(map[string]any{"items": []any{}, "total": 0, "page": 1, "page_size": 50})
	w.Owner.Get(t, w.Path("/agents/"+obj["agent_id"].(string)+"/wallet")).Expect(http.StatusOK)

	w.Owner.Delete(t, path).Expect(http.StatusNoContent)
	w.Owner.Get(t, path).Expect(http.StatusNotFound)
}

func TestOnlyAdminsAndValidation(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := newAgent(t, w)
	path := w.Path("/agents/" + agent + "/wallet")

	w.Member.Get(t, path).Expect(http.StatusForbidden)
	w.Member.Post(t, path, createBody).Expect(http.StatusForbidden)
	w.Anonymous.Get(t, path).Expect(http.StatusUnauthorized)
	w.Owner.Post(t, path, map[string]any{"wallet_type": "btc"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, path, map[string]any{"wallet_type": "mpp", "mpp_config": map[string]any{}}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, path, map[string]any{"wallet_type": "dual", "x402_config": map[string]any{}}).Expect(http.StatusBadRequest)
	w.Owner.Post(t, path, map[string]any{"wallet_type": "x402", "x402_config": map[string]any{}, "service_budget_usd": -1}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/agents/00000000-0000-0000-0000-000000000000/wallet")).Expect(http.StatusNotFound)
}
