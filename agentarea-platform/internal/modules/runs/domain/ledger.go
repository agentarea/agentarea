package domain

import (
	"regexp"
	"time"
)

// Ledger vocabulary (agentarea_tasks.domain.costs, tool_cost.Payer).
const (
	CostModel   = "model"
	CostService = "service"

	SourceTokenPricing = "token_pricing"
	SourceToolReported = "tool_reported"
	SourceReported     = "reported"
	SourceX402         = "x402"
	SourceMPP          = "mpp"

	SubjectModelInstance = "model_instance"
	SubjectTool          = "tool"

	PayerWorkspace = "workspace"
	PayerPlatform  = "platform"
	PayerPerCall   = "per_call"

	// ServiceCostCurrency is the currency wallet payments are in.
	ServiceCostCurrency = "USD"
	// ManagedByPlatform marks a provider the platform pays for.
	ManagedByPlatform = "platform"
)

// CostLine is one spend ledger line; amounts are decimal text.
type CostLine struct {
	EventID         string
	Category        string
	TaskID          string
	AgentID         string
	SubjectType     string
	SubjectID       *string
	SubjectName     *string
	CallRef         *string
	Amount          string
	Currency        string
	Source          string
	ProviderCostUSD *string
	Payer           string
	Evidence        map[string]any
	VendorCost      *string
	VendorCurrency  *string
	Estimate        bool
	OccurredAt      time.Time
	Quantity        *string
	Unit            *string
	// ClientID is the registered client a call outside a run came from.
	ClientID string
}

func uuidLike(s string) bool {
	return regexp.MustCompile(`^(?i)\{?[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\}?$|^(?i)urn:uuid:[0-9a-f-]{36}$`).MatchString(s)
}

func label(v any) *string {
	if !present(v) {
		return nil
	}
	s := []rune(pyStr(v))
	if len(s) > 255 {
		s = s[:255]
	}
	out := string(s)
	return &out
}

func optString(v any) *string {
	if !present(v) {
		return nil
	}
	s := pyStr(v)
	return &s
}

func compact(m map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range m {
		if v != nil {
			out[k] = v
		}
	}
	return out
}

// unset is v, nil when it is the empty string: a charge line without a hold or
// a settlement carries "" where Python carried None, and a stored "settle"
// key marks the line as waiting on settlement.
func unset(v any) any {
	if s, ok := v.(string); ok && s == "" {
		return nil
	}
	return v
}

// CostLines is cost_entries: the ledger lines one stored event stands for;
// none when it is not paid or names no task.
func CostLines(e StoredEvent, billingCurrency string) []CostLine {
	d := e.Data
	taskID := pyStr(d["task_id"])
	if !present(d["task_id"]) || !uuidLike(taskID) {
		return nil
	}
	agentID := ""
	if a := pyStr(d["agent_id"]); present(d["agent_id"]) && uuidLike(a) {
		agentID = a
	}
	line := func(category, amount, currency, source, subjectType string, subjectID, subjectName, callRef any) CostLine {
		return CostLine{
			EventID: e.ID, Category: category, TaskID: taskID, AgentID: agentID,
			SubjectType: subjectType, SubjectID: label(subjectID), SubjectName: label(subjectName), CallRef: label(callRef),
			Amount: amount, Currency: currency, Source: source, Payer: PayerWorkspace, OccurredAt: e.Timestamp,
		}
	}
	switch e.Type {
	case EventLLMCompleted:
		usageWrap, _ := d["usage"].(map[string]any)
		usage, _ := usageWrap["usage"].(map[string]any)
		billing, _ := usage["billing"].(map[string]any)
		raw, ok := billing["amount"]
		if !ok {
			raw = d["cost"]
		}
		amount, value := Amount(raw)
		if value.Sign() <= 0 && !present(billing["hold_id"]) {
			return nil
		}
		currency := billingCurrency
		if present(billing["currency"]) {
			currency = pyStr(billing["currency"])
		}
		l := line(CostModel, amount, currency, SourceTokenPricing, SubjectModelInstance, d["model_id"], d["model_name"], nil)
		l.VendorCost = optionalAmount(billing["vendor_cost"])
		l.VendorCurrency = optString(billing["vendor_currency"])
		l.Estimate = present(billing["estimate"])
		l.ProviderCostUSD = optionalAmount(d["provider_cost_usd"])
		if pyStr(d["managed_by"]) == ManagedByPlatform {
			l.Payer = PayerPlatform
		}
		l.Evidence = compact(map[string]any{
			"iteration": d["iteration"], "purpose": d["purpose"],
			"prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
			"total_tokens": usage["total_tokens"], "cached_prompt_tokens": usage["cached_prompt_tokens"],
			"cache_creation_tokens": usage["cache_creation_tokens"], "hold_id": unset(billing["hold_id"]), "settle": unset(billing["settle"]),
		})
		return []CostLine{l}
	case EventToolResult:
	default:
		return nil
	}
	toolEvidence := map[string]any{"source": d["source"], "server_name": d["server_name"], "iteration": d["iteration"]}
	var lines []CostLine
	if mb, ok := d["model_billing"].(map[string]any); ok {
		amount, value := Amount(mb["amount"])
		if value.Sign() > 0 || present(mb["hold_id"]) || present(mb["cost_unknown"]) {
			currency := billingCurrency
			if present(mb["currency"]) {
				currency = pyStr(mb["currency"])
			}
			l := line(CostModel, amount, currency, SourceToolReported, SubjectModelInstance, mb["model_instance_id"], d["tool_name"], d["tool_call_id"])
			l.VendorCost = optionalAmount(mb["vendor_cost"])
			l.VendorCurrency = optString(mb["vendor_currency"])
			if pyStr(mb["vendor_currency"]) == ServiceCostCurrency && !present(mb["cost_unknown"]) {
				l.ProviderCostUSD = optionalAmount(mb["vendor_cost"])
			}
			l.Estimate = present(mb["estimate"])
			if pyStr(mb["payer"]) == PayerPlatform {
				l.Payer = PayerPlatform
			}
			var unknown any
			if present(mb["cost_unknown"]) {
				unknown = mb["cost_unknown"]
			}
			l.Evidence = compact(merge(toolEvidence, map[string]any{"hold_id": unset(mb["hold_id"]), "settle": unset(mb["settle"]), "cost_unknown": unknown}))
			lines = append(lines, l)
		}
	} else if amount, value := Amount(d["model_cost"]); value.Sign() > 0 {
		l := line(CostModel, amount, billingCurrency, SourceToolReported, SubjectTool, d["server_instance_id"], d["tool_name"], d["tool_call_id"])
		l.Evidence = compact(toolEvidence)
		lines = append(lines, l)
	} else if present(d["cost_unknown"]) {
		l := line(CostModel, "0", billingCurrency, SourceToolReported, SubjectTool, d["server_instance_id"], d["tool_name"], d["tool_call_id"])
		l.Estimate = true
		l.Evidence = compact(merge(toolEvidence, map[string]any{"cost_unknown": true}))
		lines = append(lines, l)
	}
	if amount, value := Amount(d["service_cost"]); value.Sign() > 0 && !present(d["cost_metered"]) {
		payment, _ := d["payment"].(map[string]any)
		source := SourceToolReported
		switch pyStr(payment["protocol"]) {
		case "x402":
			source = SourceX402
		case "mpp":
			source = SourceMPP
		}
		kept := map[string]any{}
		for _, k := range []string{"protocol", "recipient", "tx_hash", "amount_usd"} {
			if v, ok := payment[k]; ok {
				kept[k] = v
			}
		}
		var paymentEvidence any
		if len(kept) > 0 {
			paymentEvidence = kept
		}
		l := line(CostService, amount, ServiceCostCurrency, source, SubjectTool, d["server_instance_id"], d["tool_name"], d["tool_call_id"])
		l.ProviderCostUSD = &amount
		l.Payer = PayerPerCall
		l.Evidence = compact(merge(toolEvidence, map[string]any{"payment": paymentEvidence}))
		lines = append(lines, l)
	}
	return lines
}
