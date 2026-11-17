package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"slices"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/service"
)

// PlatformTools is the policies, secrets and audit toolsets over the
// service, checking workspace admin where the tools' @requires_workspace_admin
// (or their handler) does.
type PlatformTools struct {
	Svc   *service.Service
	Admin func(ctx context.Context, c authn.Caller) error
}

var (
	_ api.PlatformPolicies = PlatformTools{}
	_ api.PlatformSecrets  = PlatformTools{}
	_ api.PlatformAudit    = PlatformTools{}
)

// errBadUUID is uuid.UUID(s)'s ValueError.
var errBadUUID = errors.New("badly formed hexadecimal UUID string")

func parseUUID(s string) (uuid.UUID, error) {
	id, err := uuid.Parse(s)
	if err != nil {
		return uuid.Nil, errBadUUID
	}
	return id, nil
}

func ruleNotFound(err error) error {
	if errors.Is(err, service.ErrRuleNotFound) {
		return api.ErrPolicyRuleNotFound
	}
	return err
}

func validationError(model string, errs []httpx.FieldError) error {
	return &httpx.ModelValidationError{Model: model, Errors: errs}
}

func ruleDocument(raw json.RawMessage) (any, error) {
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil, err
	}
	return v, nil
}

func (t PlatformTools) ListRules(ctx context.Context, c authn.Caller, f api.PolicyRuleFilter) ([]any, error) {
	if err := t.Admin(ctx, c); err != nil {
		return nil, err
	}
	var errs []httpx.FieldError
	if f.SubjectType != nil && !slices.Contains(domain.SubjectTypes(), *f.SubjectType) {
		errs = append(errs, httpx.EnumError(domain.SubjectTypes(), "subject_type"))
	}
	if f.Effect != nil && !slices.Contains(domain.Effects(), *f.Effect) {
		errs = append(errs, httpx.EnumError(domain.Effects(), "effect"))
	}
	if len(errs) > 0 {
		return nil, validationError("listArguments", errs)
	}
	rules, err := t.Svc.ListRules(ctx, c, service.Filter{SubjectType: f.SubjectType, SubjectID: f.SubjectID, Effect: f.Effect, Target: f.Target, Enabled: f.Enabled})
	if err != nil {
		return nil, err
	}
	out := make([]any, len(rules))
	for i, r := range rules {
		out[i] = ruleJSON(r)
	}
	return out, nil
}

func (t PlatformTools) GetRule(ctx context.Context, c authn.Caller, ruleID string) (any, error) {
	if err := t.Admin(ctx, c); err != nil {
		return nil, err
	}
	id, err := parseUUID(ruleID)
	if err != nil {
		return nil, err
	}
	r, err := t.Svc.GetRule(ctx, c, id)
	if err != nil {
		return nil, ruleNotFound(err)
	}
	return ruleJSON(r), nil
}

func (t PlatformTools) CreateRule(ctx context.Context, c authn.Caller, doc json.RawMessage) (any, error) {
	if err := t.Admin(ctx, c); err != nil {
		return nil, err
	}
	v, err := ruleDocument(doc)
	if err != nil {
		return nil, err
	}
	var in input
	var errs []httpx.FieldError
	ruleCreateBody(v, &in, &errs)
	if len(errs) > 0 {
		return nil, validationError("PolicyRuleCreateRequest", errs)
	}
	saved, err := t.Svc.CreateRule(ctx, c, in.rule)
	if err != nil {
		return nil, err
	}
	saved.Params = in.rule.Params
	return ruleJSON(saved), nil
}

func (t PlatformTools) UpdateRule(ctx context.Context, c authn.Caller, ruleID string, doc json.RawMessage) (any, error) {
	if err := t.Admin(ctx, c); err != nil {
		return nil, err
	}
	v, err := ruleDocument(doc)
	if err != nil {
		return nil, err
	}
	var in input
	var errs []httpx.FieldError
	ruleUpdateBody(v, &in, &errs)
	if len(errs) > 0 {
		return nil, validationError("PolicyRuleUpdateRequest", errs)
	}
	id, err := parseUUID(ruleID)
	if err != nil {
		return nil, err
	}
	r, err := t.Svc.UpdateRule(ctx, c, id, func(existing domain.Rule) domain.Rule {
		return withSent(existing, in.sent)
	}, in.patch)
	if err != nil {
		return nil, ruleNotFound(err)
	}
	if in.patch.Params != nil {
		r.Params = in.patch.Params
	}
	return ruleJSON(r), nil
}

func (t PlatformTools) DeleteRule(ctx context.Context, c authn.Caller, ruleID string) error {
	if err := t.Admin(ctx, c); err != nil {
		return err
	}
	id, err := parseUUID(ruleID)
	if err != nil {
		return err
	}
	return ruleNotFound(t.Svc.DeleteRule(ctx, c, id))
}

func (t PlatformTools) PreviewEffective(ctx context.Context, c authn.Caller, agentID string) (any, error) {
	if agentID != "" {
		id, err := parseUUID(agentID)
		if err != nil {
			return nil, err
		}
		agentID = id.String()
	}
	p, err := t.Svc.Preview(ctx, c.Workspace, agentID, nil)
	if err != nil {
		return nil, err
	}
	return p.EffectiveJSON(), nil
}

func (t PlatformTools) RunPolicy(ctx context.Context, c authn.Caller, runID string) (any, error) {
	id, err := parseUUID(runID)
	if err != nil {
		return nil, err
	}
	if !t.Svc.TaskSnapshotsWired() {
		return nil, errors.New("run policy snapshots need runs' task reader, which is not wired")
	}
	p, err := t.Svc.TaskSnapshot(ctx, c.Workspace, id.String())
	if errors.Is(err, service.ErrSnapshotNotFound) {
		return nil, api.ErrRunPolicyNotFound
	}
	if err != nil {
		return nil, err
	}
	return p.EffectiveJSON(), nil
}

func platformSecret(s secrets.Secret) api.PlatformSecret {
	return api.PlatformSecret{ID: s.ID, Name: s.Name, Description: s.Description}
}

func (t PlatformTools) ListOwn(ctx context.Context, c authn.Caller) ([]api.PlatformSecret, error) {
	list, err := t.Svc.ListOwnSecrets(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]api.PlatformSecret, len(list))
	for i, s := range list {
		out[i] = platformSecret(s)
	}
	return out, nil
}

func (t PlatformTools) Create(ctx context.Context, c authn.Caller, name, value string, description *string) (api.PlatformSecret, error) {
	if err := t.Admin(ctx, c); err != nil {
		return api.PlatformSecret{}, err
	}
	v, err := t.Svc.CreateSecret(ctx, c, name, value, description)
	if err != nil {
		return api.PlatformSecret{}, err
	}
	return platformSecret(v.Secret), nil
}

func (t PlatformTools) DeleteByName(ctx context.Context, c authn.Caller, name string) error {
	if err := t.Admin(ctx, c); err != nil {
		return err
	}
	err := t.Svc.DeleteSecretByName(ctx, c, name)
	if errors.Is(err, secrets.ErrNotFound) {
		return api.ErrNoSuchSecret
	}
	return err
}

func (t PlatformTools) List(ctx context.Context, c authn.Caller, q api.PlatformAuditQuery) ([]api.PlatformAuditEvent, error) {
	if err := t.Admin(ctx, c); err != nil {
		return nil, err
	}
	dq := domain.AuditQuery{Since: q.Since, Until: q.Until, Limit: q.Limit}
	for _, f := range []struct {
		v   string
		dst **string
	}{{q.Action, &dq.Action}, {q.ActorID, &dq.ActorID}, {q.ResourceType, &dq.ResourceType}, {q.ResourceID, &dq.ResourceID}} {
		if f.v != "" {
			v := f.v
			*f.dst = &v
		}
	}
	if q.Cursor != "" {
		id, err := parseUUID(q.Cursor)
		if err != nil {
			return nil, err
		}
		b := [16]byte(id)
		dq.Cursor = &b
	}
	events, err := t.Svc.AuditLogs(ctx, c, dq)
	if errors.Is(err, service.ErrUnknownCursor) {
		return nil, errors.New("Unknown audit cursor " + q.Cursor) //nolint:staticcheck // Python's message
	}
	if err != nil {
		return nil, err
	}
	out := make([]api.PlatformAuditEvent, len(events))
	for i, e := range events {
		out[i] = api.PlatformAuditEvent{ID: e.ID, CreatedAt: e.CreatedAt, ActorID: e.ActorID, ActorType: e.ActorType,
			Action: e.Action, ResourceType: e.ResourceType, ResourceID: e.ResourceID, RequestID: e.RequestID}
	}
	return out, nil
}
