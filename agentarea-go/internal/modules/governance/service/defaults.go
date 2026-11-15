package service

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"strconv"

	"go.yaml.in/yaml/v3"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
)

//go:embed config/default_policies.yaml
var defaultPolicies []byte

// yamlValue is a YAML node as the JSON-shaped value yaml.safe_load gives.
func yamlValue(n *yaml.Node) (any, error) {
	switch n.Kind {
	case yaml.DocumentNode:
		if len(n.Content) == 0 {
			return nil, nil
		}
		return yamlValue(n.Content[0])
	case yaml.MappingNode:
		o := wirejson.Object{}
		for i := 0; i+1 < len(n.Content); i += 2 {
			v, err := yamlValue(n.Content[i+1])
			if err != nil {
				return nil, err
			}
			o.Set(n.Content[i].Value, v)
		}
		return o, nil
	case yaml.SequenceNode:
		out := make([]any, 0, len(n.Content))
		for _, c := range n.Content {
			v, err := yamlValue(c)
			if err != nil {
				return nil, err
			}
			out = append(out, v)
		}
		return out, nil
	case yaml.AliasNode:
		return yamlValue(n.Alias)
	case yaml.ScalarNode:
		switch n.Tag {
		case "!!null":
			return nil, nil
		case "!!bool":
			var b bool
			err := n.Decode(&b)
			return b, err
		case "!!int":
			var i int64
			if err := n.Decode(&i); err != nil {
				return nil, err
			}
			return json.Number(strconv.FormatInt(i, 10)), nil
		case "!!float":
			var f float64
			err := n.Decode(&f)
			return wirejson.Float(f), err
		}
		return n.Value, nil
	}
	return nil, fmt.Errorf("unsupported YAML node kind %d", n.Kind)
}

// defaultSpecs is load_default_policy_specs: the packaged baseline, or the
// file at DefaultPoliciesPath; a missing file is an error, never an empty set.
func (sv *Service) defaultSpecs() ([]any, string, error) {
	raw, where := defaultPolicies, "config/default_policies.yaml"
	if p := sv.d.DefaultPoliciesPath; p != "" {
		b, err := os.ReadFile(p) //nolint:gosec // an operator-chosen path
		if err != nil {
			return nil, p, fmt.Errorf("required governance baseline not found: %s: %w", p, err)
		}
		raw, where = b, p
	}
	var doc yaml.Node
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		return nil, where, err
	}
	v, err := yamlValue(&doc)
	if err != nil {
		return nil, where, err
	}
	specs, ok := api.Field(v, "policies")
	if !ok || specs == nil {
		return nil, where, nil
	}
	list, ok := specs.([]any)
	if !ok {
		return nil, where, fmt.Errorf("'policies' in %s must be a list", where)
	}
	return list, where, nil
}

// DefaultRules is default_policy_rules: the baseline bound to the workspace.
func (sv *Service) DefaultRules(workspaceID string) ([]domain.Rule, error) {
	specs, where, err := sv.defaultSpecs()
	if err != nil {
		return nil, err
	}
	out := make([]domain.Rule, 0, len(specs))
	for i, spec := range specs {
		str := func(key string) (string, bool) {
			v, _ := api.Field(spec, key)
			s, ok := v.(string)
			return s, ok
		}
		target, ok1 := str("target")
		effect, ok2 := str("effect")
		if !ok1 || !ok2 {
			return nil, fmt.Errorf("default policy %d in %s needs a target and an effect", i, where)
		}
		r := domain.Rule{SubjectType: "workspace", SubjectID: workspaceID, Target: target, Effect: effect, Enabled: true, Params: api.EmptyObject()}
		if !r.Known() {
			return nil, fmt.Errorf("default policy %d in %s: unknown effect %q", i, where, effect)
		}
		if v, ok := api.Field(spec, "params"); ok {
			r.Params = v
		}
		if v, ok := str("condition"); ok {
			r.Condition = &v
		}
		if v, ok := api.Field(spec, "enabled"); ok {
			b, isBool := v.(bool)
			if !isBool {
				return nil, fmt.Errorf("default policy %d in %s: enabled must be a boolean", i, where)
			}
			r.Enabled = b
		}
		if v, ok := api.Field(spec, "priority"); ok {
			n, isInt := v.(json.Number)
			p, err := n.Int64()
			if !isInt || err != nil {
				return nil, fmt.Errorf("default policy %d in %s: priority must be an integer", i, where)
			}
			r.Priority = p
		}
		out = append(out, r)
	}
	return out, nil
}

// dimension is _dimension_key: a baseline row's identity, fine enough to
// tell the month and run spend caps and the scoped caps apart.
func dimension(r domain.Rule) string {
	parts := []any{r.Target, r.Effect}
	for _, k := range []string{"period", "client_id", "connection_id", "tool", "currency", "category"} {
		v, _ := api.Field(r.Params, k)
		parts = append(parts, api.PyRepr(v))
	}
	return fmt.Sprint(parts...)
}

// ProvisionDefaults is provision_default_policies, run in the transaction
// that inserts the workspace: the baseline dimensions it lacks are added as
// rules created by creatorUserID, each audited. Matches
// identity's WorkspaceCreated hook.
func (sv *Service) ProvisionDefaults(ctx context.Context, q db.Querier, ws scope.Workspace, creatorUserID string) error {
	s := db.NewTxSession(ws, q)
	wsType := "workspace"
	wsID := ws.ID()
	existing, err := sv.d.Policies.List(ctx, s, Filter{SubjectType: &wsType, SubjectID: &wsID})
	if err != nil {
		return err
	}
	have := map[string]bool{}
	for _, r := range sv.known(ctx, existing) {
		have[dimension(r)] = true
	}
	rules, err := sv.DefaultRules(wsID)
	if err != nil {
		return err
	}
	seeded := 0
	for _, r := range rules {
		if have[dimension(r)] {
			continue
		}
		created, err := sv.createRule(ctx, s, creatorUserID, r)
		if err != nil {
			return err
		}
		if err := sv.recordSystem(ctx, s, creatorUserID, "governance_policy.create", created.ID); err != nil {
			sv.d.Log.WarnContext(ctx, "Failed to record audit event", "action", "governance_policy.create", "error", err)
		}
		seeded++
	}
	if seeded > 0 {
		sv.d.Log.InfoContext(ctx, "seeded default policies", "count", seeded, "workspace_id", wsID)
	}
	return nil
}
