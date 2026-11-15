package mcpserver

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

func policyError(err error) error {
	switch {
	case errors.Is(err, governanceapi.ErrPolicyRuleNotFound), errors.Is(err, governanceapi.ErrRunPolicyNotFound):
		return &toolError{err.Error()}
	}
	return err
}

type ruleIDArgs struct {
	RuleID string `json:"rule_id"`
}

// policyTools is tools/policies_toolset.py.
func policyTools(p governanceapi.PlatformPolicies) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List policy rules", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				SubjectType *string `json:"subject_type"`
				SubjectID   *string `json:"subject_id"`
				Effect      *string `json:"effect"`
				Target      *string `json:"target"`
				Enabled     *bool   `json:"enabled"`
			}](args)
			if err != nil {
				return nil, err
			}
			f := governanceapi.PolicyRuleFilter{SubjectType: in.SubjectType, SubjectID: in.SubjectID, Effect: in.Effect, Target: in.Target, Enabled: in.Enabled}
			// Python filters on a subject type or effect only when it is truthy.
			if f.SubjectType != nil && *f.SubjectType == "" {
				f.SubjectType = nil
			}
			if f.Effect != nil && *f.Effect == "" {
				f.Effect = nil
			}
			rules, err := p.ListRules(ctx, c, f)
			if err != nil {
				return nil, err
			}
			if rules == nil {
				rules = []any{}
			}
			return rules, nil
		}},
		"get": {title: "Get policy rule", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[ruleIDArgs](args)
			if err != nil {
				return nil, err
			}
			r, err := p.GetRule(ctx, c, in.RuleID)
			return r, policyError(err)
		}},
		"create": {title: "Create policy rule", effect: effectPrivileged, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[map[string]json.RawMessage](args)
			if err != nil {
				return nil, err
			}
			doc := map[string]json.RawMessage{"params": json.RawMessage(`{}`), "condition": json.RawMessage(`null`),
				"enabled": json.RawMessage(`true`), "priority": json.RawMessage(`0`)}
			for _, k := range []string{"subject_type", "subject_id", "target", "effect", "params", "condition", "enabled", "priority"} {
				if v, ok := in[k]; ok {
					doc[k] = v
				}
			}
			if string(doc["params"]) == "null" {
				doc["params"] = json.RawMessage(`{}`)
			}
			raw, err := json.Marshal(doc)
			if err != nil {
				return nil, err
			}
			r, err := p.CreateRule(ctx, c, raw)
			return r, policyError(err)
		}},
		"update": {title: "Update policy rule", effect: effectPrivileged, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[ruleIDArgs](args)
			if err != nil {
				return nil, err
			}
			patch, err := patchArgs(args, []string{"rule_id"},
				[]string{"subject_type", "subject_id", "target", "effect", "params", "condition", "enabled", "priority"})
			if err != nil {
				return nil, err
			}
			r, err := p.UpdateRule(ctx, c, in.RuleID, patch)
			return r, policyError(err)
		}},
		"delete": {title: "Delete policy rule", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[ruleIDArgs](args)
			if err != nil {
				return nil, err
			}
			if err := p.DeleteRule(ctx, c, in.RuleID); err != nil {
				return nil, policyError(err)
			}
			return map[string]any{"deleted": true}, nil
		}},
		"preview_effective_policy": {title: "Preview effective policy", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				AgentID *string `json:"agent_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			agentID := ""
			if in.AgentID != nil {
				agentID = *in.AgentID
			}
			return p.PreviewEffective(ctx, c, agentID)
		}},
		"get_run_policy": {title: "Get run policy", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				RunID string `json:"run_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			r, err := p.RunPolicy(ctx, c, in.RunID)
			return r, policyError(err)
		}},
	}
}
