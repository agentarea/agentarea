//go:build suite

package runs

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

// x402API is an API whose answer costs 0.01 USDC over x402 v2: unsigned
// requests get the 402 challenge, a signed one the answer and a receipt.
type x402API struct {
	mu         sync.Mutex
	challenges int
	signatures []string
}

func (a *x402API) serve(t *testing.T) string {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sig := r.Header.Get("PAYMENT-SIGNATURE")
		a.mu.Lock()
		if sig == "" {
			a.challenges++
		} else {
			a.signatures = append(a.signatures, sig)
		}
		a.mu.Unlock()
		if sig == "" {
			required, _ := json.Marshal(map[string]any{
				"x402Version": 2,
				"resource":    map[string]any{"url": "http://" + r.Host + r.URL.Path},
				"accepts": []any{map[string]any{
					"scheme": "exact", "network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
					"amount": "10000", "payTo": "0x209693Bc6afc0C5328bA36FaF03C514EF312287C", "maxTimeoutSeconds": 60,
					"extra": map[string]any{"name": "USD Coin", "version": "2"},
				}},
			})
			w.Header().Set("PAYMENT-REQUIRED", base64.StdEncoding.EncodeToString(required))
			w.WriteHeader(http.StatusPaymentRequired)
			_, _ = w.Write([]byte(`{"error":"payment required"}`))
			return
		}
		receipt, _ := json.Marshal(map[string]any{"success": true, "transaction": "0xsuitepaid"})
		w.Header().Set("PAYMENT-RESPONSE", base64.StdEncoding.EncodeToString(receipt))
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"answer":42}`))
	}))
	t.Cleanup(srv.Close)
	return h.StackURL(srv.URL)
}

// An agent with an x402 wallet pays the 402 its OpenAPI tool meets: the call
// is retried signed, the answer reaches the model, and the wallet records the
// completed payment against its budget.
func TestAnAgentPaysA402FromItsWallet(t *testing.T) {
	w := h.NewWorkspace(t)
	host := &fakeHost{}
	base := host.serve(t)
	paid := &x402API{}
	apiBase := paid.serve(t)
	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": suiteProvider, "name": "Fake", "api_key": "sk-suite", "endpoint_url": base,
	}).Expect(http.StatusOK).Object()
	inst := w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": suiteChat, "name": "Fake chat",
	}).Expect(http.StatusOK).Object()
	conn := w.Owner.Post(t, w.Path("/openapi-connections/"), map[string]any{
		"name": "Paid answers", "base_url": apiBase, "spec_content": answerAPI(),
	}).Expect(http.StatusCreated).Object()
	agent := w.Owner.Post(t, w.Path("/agents/"), map[string]any{
		"name": "Payer", "instruction": "Answer the question.", "model_id": inst["id"],
		"tools": []any{map[string]any{"type": "openapi", "name": "Paid answers", "settings": map[string]any{"openapi_connection_id": conn["id"]}}},
	}).Expect(http.StatusOK, http.StatusCreated).Object()["id"].(string)
	wallet := w.Path("/agents/" + agent + "/wallet")
	w.Owner.Post(t, wallet, map[string]any{
		"wallet_type": "x402", "x402_config": map[string]any{},
		"credentials":        map[string]any{"x402_private_key": "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"},
		"service_budget_usd": 5, "service_budget_period": "daily",
	}).Expect(http.StatusCreated)

	tasks := "/agents/" + agent + "/tasks/"
	task := w.Owner.Post(t, w.Path(tasks+"sync"), map[string]any{
		"description": "What is the suite answer?",
		"task_policy": map[string]any{
			"budget":    map[string]any{"run_budget_usd": "1.00"},
			"tokens":    map[string]any{"max_tokens": 10000, "max_tokens_per_call": 1000},
			"execution": map[string]any{"max_model_turns": 5, "max_tool_calls_per_turn": 2, "max_tool_calls_total": 5},
		},
	}).Expect(http.StatusOK).Object()
	taskID, _ := task["id"].(string)
	h.Eventually(t, 90*time.Second, func() error {
		final := w.Owner.Get(t, w.Path(tasks+taskID)).Expect(http.StatusOK).Object()
		switch final["status"] {
		case "completed":
			return nil
		case "failed", "cancelled", "canceled":
			t.Fatalf("task ended %v: %v", final["status"], final)
		}
		return fmt.Errorf("status %v", final["status"])
	})

	paid.mu.Lock()
	challenges, signatures := paid.challenges, len(paid.signatures)
	paid.mu.Unlock()
	if challenges != 1 || signatures != 1 {
		t.Fatalf("the API saw %d unpaid and %d paid requests, want 1 and 1", challenges, signatures)
	}
	_, byType := taskEvents(t, w.Owner.Get(t, w.Path(tasks+taskID+"/events")).Expect(http.StatusOK).JSON())
	if r := byType["tool.result"]; r["success"] != true || !strings.Contains(fmt.Sprint(r["result"]), "42") {
		t.Fatalf("tool.result %v", r)
	}
	page := w.Owner.Get(t, wallet+"/payments").Expect(http.StatusOK).Object()
	items, _ := page["items"].([]any)
	if len(items) != 1 {
		t.Fatalf("payments %v", page)
	}
	p, _ := items[0].(map[string]any)
	if p["status"] != "completed" || p["protocol"] != "x402" || p["amount_usd"] != "0.010000" || p["tx_hash"] != "0xsuitepaid" {
		t.Fatalf("payment %v", p)
	}
	w.Owner.Get(t, wallet+"/balance").Expect(http.StatusOK).Match(map[string]any{
		"service_budget_usd": "5.000000", "service_budget_period": "daily", "total_spent_current_period": "0.010000", "remaining": "4.990000",
	})
}
