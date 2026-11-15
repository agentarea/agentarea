package service

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
)

const (
	modelConnector   = "llm"
	providerCurrency = "USD"
	settleCapture    = "capture"
	settleConvert    = "convert"
)

// funding is who pays one model call: billing's hold when the platform does.
type funding struct {
	modelID        string
	platformFunded bool
	holdID         string
	held           money.Decimal
	heldCurrency   string
	estimate       money.Decimal
}

// billingRefusal is a gate verdict the workflow reads as the entitlement gate's: never retried.
func billingRefusal(code, reason, phase string) error {
	return nonRetryable("GovernanceDeniedError", "billing: "+reason, nil, map[string]any{
		"interceptor_name": "billing", "reason": reason, "metadata": map[string]any{"entitlement_code": code}, "phase": phase,
	})
}

// estimateVendorCost is the most a call can cost: its prompt, roughly, and every output token; nil when unpriced.
func estimateVendorCost(messages []domain.ModelMessage, maxTokens int, prices api.ModelPrices) *money.Decimal {
	if prices.Input == nil || prices.Output == nil {
		return nil
	}
	b, _ := json.Marshal(messages)
	prompt := money.FromInt(int64(len(b) / 4))
	v := prompt.Mul(*prices.Input).Add(money.FromInt(int64(maxTokens)).Mul(*prices.Output))
	return &v
}

func (s *Service) billingCtx(ctx context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(ctx, money.BillingTimeout)
}

// holdModelCall funds a call before its credential is read (hold_model_call).
func (s *Service) holdModelCall(ctx context.Context, p Principal, model api.ResolvedModel, estimate *money.Decimal, key string) (funding, error) {
	f := funding{modelID: model.ModelID, platformFunded: model.ManagedBy == domain.ManagedByPlatform}
	if !f.platformFunded || s.d.Billing == nil {
		return f, nil
	}
	if estimate == nil {
		return f, billingRefusal("model_unpriced", fmt.Sprintf("model %s declares no price to hold a call on the platform's credentials against", model.ModelID), "pre_llm_call")
	}
	bctx, cancel := s.billingCtx(ctx)
	defer cancel()
	hold, err := s.d.Billing.Authorize(bctx, money.AuthorizeRequest{
		WorkspaceID: p.WorkspaceID, Connector: modelConnector, Tool: model.ModelID, VendorCost: *estimate,
		VendorCurrency: providerCurrency, Quantity: money.FromInt(1), Unit: "call", IdempotencyKey: key, Kind: money.KindModel,
	})
	if err != nil {
		s.d.Log.ErrorContext(ctx, "billing could not authorize the model call", "model", model.ModelID, "error", err)
		return f, billingRefusal("billing_unavailable", "billing is temporarily unavailable", "pre_llm_call")
	}
	if !hold.Allowed {
		return f, billingRefusal(hold.Code, hold.Reason, "pre_llm_call")
	}
	f.holdID, f.heldCurrency, f.estimate = hold.HoldID, string(hold.Currency), *estimate
	if hold.Amount != nil {
		f.held = *hold.Amount
	}
	return f, nil
}

// releaseHold voids the hold of a call that did not run to an answer; a failure leaves it to its TTL.
func (s *Service) releaseHold(ctx context.Context, f funding, why string) {
	if f.holdID == "" || s.d.Billing == nil {
		return
	}
	bctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), money.BillingTimeout)
	defer cancel()
	if err := s.d.Billing.Void(bctx, f.holdID); err != nil {
		s.d.Log.ErrorContext(ctx, "hold could not be voided; it expires", "hold_id", f.holdID, "why", why, "error", err)
	}
}

// chargeModelCall is the line one finished call writes from its vendor cost in USD (charge_model_call).
func (s *Service) chargeModelCall(ctx context.Context, f funding, vendorCost money.Decimal) (ChargeLine, error) {
	line := ChargeLine{ModelInstanceID: f.modelID, VendorCost: vendorCost, VendorCurrency: providerCurrency, PlatformFunded: f.platformFunded}
	line.Payer = domain.PayerWorkspace
	if f.platformFunded {
		line.Payer = domain.PayerPlatform
	}
	if f.holdID != "" {
		line.Amount, line.Currency, line.Estimate, line.Settle, line.HoldID = f.held, f.heldCurrency, true, settleCapture, f.holdID
		bctx, cancel := s.billingCtx(ctx)
		defer cancel()
		quotes, err := s.d.Billing.Quote(bctx, []money.QuoteLine{{
			Payer: "platform", Connector: modelConnector, Tool: f.modelID, VendorCost: vendorCost,
			VendorCurrency: providerCurrency, Kind: money.KindModel,
		}})
		switch {
		case err != nil:
			s.d.Log.ErrorContext(ctx, "billing could not price the model call now; the line keeps its hold", "model", f.modelID, "error", err)
		case len(quotes) == 1 && quotes[0].Amount != nil:
			line.Amount, line.Currency = *quotes[0].Amount, string(s.d.Billing.Currency())
		default:
			s.d.Log.ErrorContext(ctx, "billing does not price a model it held; the line keeps the hold", "model", f.modelID)
		}
		return line, nil
	}
	if f.platformFunded {
		if s.d.Billing != nil {
			return ChargeLine{}, nonRetryable("ModelChargeUnavailableError", fmt.Sprintf("model usage accounting unavailable: model %s ran on the platform's credentials without a hold", f.modelID), nil)
		}
		line.Amount, line.Currency = vendorCost, providerCurrency
		return line, nil
	}
	amount, currency, pending := s.convertCost(ctx, "workspace", modelConnector, f.modelID, vendorCost, providerCurrency, money.KindModel)
	line.Amount, line.Currency = amount, currency
	if pending {
		line.Estimate, line.Settle = true, settleConvert
	}
	return line, nil
}

// convertCost is a cost on the payer's own money in the deployment currency,
// without markup; without billing it stays in its own currency (convert_cost).
// pending: billing could not convert it now; settlement will.
func (s *Service) convertCost(ctx context.Context, payer, connector, tool string, vendorCost money.Decimal, vendorCurrency string, kind money.BillingKind) (money.Decimal, string, bool) {
	currency := string(s.d.Pricing.Currency())
	if currency == vendorCurrency || s.d.Billing == nil {
		return vendorCost, vendorCurrency, false
	}
	bctx, cancel := s.billingCtx(ctx)
	defer cancel()
	quotes, err := s.d.Billing.Quote(bctx, []money.QuoteLine{{
		Payer: "workspace", Connector: connector, Tool: tool, VendorCost: vendorCost,
		VendorCurrency: money.Currency(vendorCurrency), Kind: kind,
	}})
	if err != nil || len(quotes) != 1 {
		s.d.Log.ErrorContext(ctx, "a cost could not be converted now; left for settlement", "connector", connector, "tool", tool, "payer", payer, "from", vendorCurrency, "to", currency, "error", err)
		return vendorCost, vendorCurrency, true
	}
	if quotes[0].Amount == nil {
		s.d.Log.WarnContext(ctx, "billing cannot express a cost in the deployment currency; not covered by caps", "connector", connector, "tool", tool, "from", vendorCurrency, "code", quotes[0].Code)
		return vendorCost, vendorCurrency, false
	}
	return *quotes[0].Amount, currency, false
}

// chunkPublisher turns streamed deltas into cumulative llm.call.chunk
// snapshots on the task's live channel, at most one per interval; the final
// one and the first after a switch between text and thinking always go out.
func (s *Service) chunkPublisher(ctx context.Context, taskID, executionID string, iteration int, streamText bool) func(modelsapi.Chunk) {
	var text, thinking, publishedType string
	var publishedAt time.Time
	return func(c modelsapi.Chunk) {
		chunkType := "text"
		if c.Thinking {
			chunkType = "thinking"
			thinking += c.Delta
		} else {
			text += c.Delta
		}
		if !streamText && chunkType == "text" && publishedType == "text" && !c.Final {
			return
		}
		now := time.Now()
		if !c.Final && !publishedAt.IsZero() && chunkType == publishedType && now.Sub(publishedAt) < 100*time.Millisecond {
			return
		}
		publishedAt, publishedType = now, chunkType
		shown := text
		if !streamText {
			shown = ""
		}
		e := taskEvent(taskID, "", domain.EventLLMChunk, newID(), s.now(), map[string]any{
			"task_id": taskID, "execution_id": executionID, "iteration": iteration, "chunk": shown,
			"thinking": thinking, "chunk_index": c.Index, "is_final": c.Final, "chunk_type": chunkType,
		}, nil)
		if err := s.d.Events.Broadcast(ctx, e); err != nil {
			s.d.Log.ErrorContext(ctx, "failed to publish a chunk event", "task_id", taskID, "error", err)
		}
	}
}
