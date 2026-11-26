package service

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

var _ api.OneShotModels = (*Service)(nil)

func (s *Service) oneShotPrincipal(ws scope.Workspace, who api.ModelCallFor) (Principal, error) {
	if s.d.Describer == nil {
		return Principal{}, errors.New("model calls outside a run are not wired")
	}
	if who.AgentID == "" || who.UserID == "" {
		return Principal{}, fmt.Errorf("a model call outside a run needs its user and agent (user %q, agent %q)", who.UserID, who.AgentID)
	}
	return Principal{WorkspaceID: ws.ID(), UserID: who.UserID, AgentID: who.AgentID}, nil
}

// Chat is LLMConditionEvaluator._call_llm: one prompt at temperature 0.1, held, charged and
// written to the ledger.
func (s *Service) Chat(ctx context.Context, ws scope.Workspace, who api.ModelCallFor, in api.ChatOnce) (string, error) {
	p, err := s.oneShotPrincipal(ws, who)
	if err != nil {
		return "", err
	}
	model, err := s.d.Describer.Describe(ctx, modelsapi.Principal(p), in.ModelID, modelsapi.KindChat)
	if err != nil {
		return "", oneShotFailure(err)
	}
	messages := []domain.ModelMessage{{Role: "user", Content: in.Prompt}}
	if err := s.refuseAtSpendCap(ctx, p, nil, modelCall{Model: model.ModelName}); err != nil {
		return "", oneShotFailure(err)
	}
	f, err := s.holdModelCall(ctx, p, model, estimateVendorCost(messages, in.MaxTokens, model.Prices), "trigger:"+strings.ReplaceAll(newID(), "-", ""))
	if err != nil {
		return "", oneShotFailure(err)
	}
	temperature := in.Temperature
	reply, err := s.d.Models.Call(ctx, modelsapi.Principal(p), modelsapi.Call{
		Model: model, Messages: modelMessages(messages), Temperature: &temperature, MaxTokens: in.MaxTokens, Funded: f.platformFunded,
	})
	if err != nil {
		s.releaseHold(ctx, f, "the "+who.Purpose+" call did not complete")
		return "", oneShotFailure(err)
	}
	var provider *money.Decimal
	if reply.ProviderCostUSD.Sign() != 0 {
		provider = &reply.ProviderCostUSD
	}
	charge, err := s.chargeModelCall(ctx, f, reply.ProviderCostUSD)
	if err != nil {
		return "", err
	}
	if err := s.recordOneShot(ctx, ws, who, model, charge, provider); err != nil {
		return "", err
	}
	return strings.TrimSpace(reply.Content), nil
}

// Decide is LLMConditionEvaluator._decide_condition's call: one System One request, held,
// charged and written to the ledger.
func (s *Service) Decide(ctx context.Context, ws scope.Workspace, who api.ModelCallFor, in api.DecideOnce) (map[string]map[string]any, error) {
	p, err := s.oneShotPrincipal(ws, who)
	if err != nil {
		return nil, err
	}
	if s.d.Decider == nil {
		return nil, errors.New("decision model calls are not wired")
	}
	model, err := s.d.Describer.Describe(ctx, modelsapi.Principal(p), in.ModelID, modelsapi.KindDecision)
	if err != nil {
		return nil, oneShotFailure(err)
	}
	if err := s.refuseAtSpendCap(ctx, p, nil, modelCall{Model: model.ModelName}); err != nil {
		return nil, oneShotFailure(err)
	}
	maxOut := 0
	if model.MaxOutputTokens != nil {
		maxOut = *model.MaxOutputTokens
	}
	request := []domain.ModelMessage{{Role: "user", Content: decisionRequestText(in)}}
	f, err := s.holdModelCall(ctx, p, model, estimateVendorCost(request, maxOut, model.Prices), "trigger:"+strings.ReplaceAll(newID(), "-", ""))
	if err != nil {
		return nil, oneShotFailure(err)
	}
	reply, err := s.d.Decider.Decide(ctx, modelsapi.Principal(p), modelsapi.Decision{Model: model, Funded: f.platformFunded, State: in.State, Questions: in.Questions})
	if err != nil {
		s.releaseHold(ctx, f, "the decision call did not complete")
		return nil, oneShotFailure(err)
	}
	var charge ChargeLine
	if reply.CostUSD == nil {
		charge = s.chargeUnknownCost(ctx, f)
	} else if charge, err = s.chargeModelCall(ctx, f, *reply.CostUSD); err != nil {
		return nil, err
	}
	if err := s.recordOneShot(ctx, ws, who, model, charge, reply.CostUSD); err != nil {
		return nil, err
	}
	return reply.Answers, nil
}

// decisionRequestText is the request as decision_estimate measures it: state and questions.
func decisionRequestText(in api.DecideOnce) string {
	return string(domain.PyDumpsCanonical(map[string]any{"state": in.State, "questions": in.Questions}))
}

// chargeUnknownCost is charge_model_call with no vendor cost: a held call comes to its held
// amount, any other to nothing, both marked cost_unknown.
func (s *Service) chargeUnknownCost(ctx context.Context, f funding) ChargeLine {
	if f.holdID != "" {
		s.d.Log.ErrorContext(ctx, "model reported no cost; its line is the held amount", "model", f.modelID)
		return ChargeLine{ModelInstanceID: f.modelID, Model: f.modelName, Amount: f.held, Currency: f.heldCurrency, VendorCost: f.estimate, VendorCurrency: providerCurrency,
			Estimate: true, Settle: settleCapture, HoldID: f.holdID, CostUnknown: true, PlatformFunded: true, Payer: domain.PayerPlatform}
	}
	s.d.Log.ErrorContext(ctx, "model reported no cost; its cost is unknown", "model", f.modelID)
	payer := domain.PayerWorkspace
	if f.platformFunded {
		payer = domain.PayerPlatform
	}
	zero := money.FromInt(0)
	return ChargeLine{ModelInstanceID: f.modelID, Model: f.modelName, Amount: zero, Currency: providerCurrency, VendorCost: zero, VendorCurrency: providerCurrency,
		Estimate: true, CostUnknown: true, PlatformFunded: f.platformFunded, Payer: payer}
}

// recordOneShot is LLMConditionEvaluator._record: a line for a call that cost something, was
// held, or whose cost is unknown. Unlike Python it names the agent whose caps the call fell
// under, so the agent's caps count it.
func (s *Service) recordOneShot(ctx context.Context, ws scope.Workspace, who api.ModelCallFor, model modelsapi.ResolvedModel, c ChargeLine, provider *money.Decimal) error {
	if c.Amount.Sign() <= 0 && c.HoldID == "" && !c.CostUnknown {
		return nil
	}
	evidence := map[string]any{"purpose": who.Purpose, "trigger_id": nil}
	if who.TriggerID != "" {
		evidence["trigger_id"] = who.TriggerID
	}
	if c.HoldID != "" {
		evidence["hold_id"] = c.HoldID
	}
	if c.Settle != "" {
		evidence["settle"] = c.Settle
	}
	if c.CostUnknown {
		evidence["cost_unknown"] = true
	}
	name := model.ModelName
	if len(name) > 255 {
		name = name[:255]
	}
	vendorCost, vendorCurrency := c.VendorCost.String(), c.VendorCurrency
	line := domain.CostLine{
		EventID: newID(), Category: domain.CostModel, AgentID: who.AgentID, SubjectType: domain.SubjectModelInstance,
		SubjectID: &c.ModelInstanceID, SubjectName: &name, Amount: c.Amount.String(), Currency: c.Currency, Source: domain.SourceTokenPricing,
		Payer: c.Payer, Evidence: evidence, VendorCost: &vendorCost, VendorCurrency: &vendorCurrency, Estimate: c.Estimate, OccurredAt: s.now(),
	}
	if provider != nil {
		v := provider.String()
		line.ProviderCostUSD = &v
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		_, err := s.store.InsertCostLine(ctx, tx, line, who.UserID, store.TaskRef{})
		return err
	})
}

// oneShotFailure is what _call_llm raises: billing's or the spend cap's own words, else the
// failure without what the provider answered.
func oneShotFailure(err error) error {
	var app *durable.ApplicationError
	if errors.As(err, &app) {
		switch app.Type {
		case "SpendCapReachedError":
			return &api.ModelCallRefused{Msg: app.Message}
		case "GovernanceDeniedError":
			return &api.ModelCallRefused{Msg: strings.TrimPrefix(app.Message, "billing: ")}
		}
	}
	var callErr *modelsapi.ModelCallError
	if errors.As(err, &callErr) {
		return &api.ModelCallFailed{Detail: callErr.Msg}
	}
	if errors.Is(err, modelsapi.ErrNotFound) || errors.Is(err, modelsapi.ErrRefused) || errors.Is(err, modelsapi.ErrKindMismatch) {
		return &api.ModelCallFailed{Detail: err.Error()}
	}
	var status modelsapi.HTTPStatusError
	if errors.As(err, &status) {
		return &api.ModelCallFailed{Detail: fmt.Sprintf("HTTP %d", status.HTTPStatus())}
	}
	if app != nil && app.Type != "" {
		return &api.ModelCallFailed{Detail: app.Type}
	}
	if errors.Is(err, context.Canceled) {
		return err
	}
	return &api.ModelCallFailed{Detail: "the call failed"}
}
