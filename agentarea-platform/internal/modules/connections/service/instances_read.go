package service

import (
	"context"
	"errors"
	"sync"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/toolname"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// Consumer is MCPInstanceConsumer: an agent attaching the instance.
type Consumer struct {
	AgentID      string
	AgentName    string
	AgentSlug    string
	EnabledTools []string
	ConfirmTools []string
}

// mcpToolTicked is mcp_tool_ticked: an approval rule on the tool, old spelling included.
func mcpToolTicked(serverRef, tool string, targets map[string]bool) bool {
	return targets["tool:"+toolname.MCPToolTarget(serverRef, tool)] || targets["tool:"+tool]
}

// Consumers is GET /consumers: the agents whose saved tools attach the
// instance, with the tools they enabled and which of those need confirmation.
func (s *Service) Consumers(ctx context.Context, c authn.Caller, id uuid.UUID) ([]Consumer, error) {
	inst, err := s.GetInstance(ctx, c, id)
	if err != nil {
		return nil, err
	}
	uses, err := s.d.Agents.MCPConsumers(ctx, c.Workspace, inst.ID, inst.Name)
	if err != nil {
		return nil, err
	}
	agentIDs := make([]string, 0, len(uses))
	for _, u := range uses {
		agentIDs = append(agentIDs, u.AgentID)
	}
	targets, err := s.d.Approvals.Targets(ctx, c.Workspace, agentIDs)
	if err != nil {
		return nil, err
	}
	out := make([]Consumer, 0, len(uses))
	for _, u := range uses {
		ticked := map[string]bool{}
		for _, t := range targets[u.AgentID] {
			ticked[t] = true
		}
		confirm := []string{}
		for _, name := range u.EnabledTools {
			if mcpToolTicked(u.ServerRef, name, ticked) {
				confirm = append(confirm, name)
			}
		}
		out = append(out, Consumer{AgentID: u.AgentID, AgentName: u.AgentName, AgentSlug: u.AgentSlug,
			EnabledTools: u.EnabledTools, ConfirmTools: confirm})
	}
	return out, nil
}

// toolNames is _instance_tool_names: each advertised tool's name once.
func toolNames(inst domain.Instance) []string {
	var out []string
	for _, t := range inst.AvailableTools() {
		m, ok := t.(map[string]any)
		if !ok {
			continue
		}
		if n, ok := m["name"].(string); ok && n != "" && !contains(out, n) {
			out = append(out, n)
		}
	}
	return out
}

func (s *Service) instanceToolPolicies(inst domain.Instance, rules []WorkspaceRule, p governanceapi.Policy) []ToolPolicy {
	names := toolNames(inst)
	out := make([]ToolPolicy, 0, len(names))
	for _, n := range names {
		out = append(out, ToolPolicyOf(n, "tool:"+toolname.MCPToolTarget(inst.ID, globLiteral(n)),
			toolname.MCPToolTarget(inst.ID, n), toolname.MCPNarrowingNames(inst.Name, n), rules, p))
	}
	return out
}

// InstanceToolPolicies is GET /{id}/tool-policies.
func (s *Service) InstanceToolPolicies(ctx context.Context, c authn.Caller, id uuid.UUID) ([]ToolPolicy, error) {
	inst, err := s.GetInstance(ctx, c, id)
	if err != nil {
		return nil, err
	}
	rules, p, err := s.d.Policies.Workspace(ctx, c)
	if err != nil {
		return nil, err
	}
	return s.instanceToolPolicies(inst, rules, p), nil
}

// InstanceTools is one instance's tools on the agent editor.
type InstanceTools struct {
	InstanceID string
	Tools      []ToolPolicy
}

// WorkspaceToolPolicies is GET /tool-policies: every instance's tools in one read.
func (s *Service) WorkspaceToolPolicies(ctx context.Context, c authn.Caller) ([]InstanceTools, error) {
	rows, _, err := s.listInstances(ctx, c)
	if err != nil {
		return nil, err
	}
	rules, p, err := s.d.Policies.Workspace(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]InstanceTools, 0, len(rows))
	for _, r := range rows {
		out = append(out, InstanceTools{InstanceID: r.ID, Tools: s.instanceToolPolicies(r, rules, p)})
	}
	return out, nil
}

// InstanceEnvironment is get_instance_environment: the names of the
// instance's env vars that hold a value; none for an instance it cannot see.
func (s *Service) InstanceEnvironment(ctx context.Context, c authn.Caller, id uuid.UUID) ([]string, error) {
	out := []string{}
	err := s.read(ctx, c, func(sess db.Session) error {
		inst, ok, err := s.d.Instances.Get(ctx, sess, id)
		if err != nil || !ok {
			return err
		}
		m := s.d.Secrets.Manager(sess, c.UserID)
		for _, n := range inst.EnvVars() {
			v, err := m.Get(ctx, domain.InstanceSecretName(inst.ID, n))
			if errors.Is(err, ksecrets.ErrNotFound) {
				continue
			}
			if err != nil {
				return err
			}
			if v != "" && !contains(out, n) {
				out = append(out, n)
			}
		}
		return nil
	})
	return out, err
}

// ContainerHealth is one workload's health as the workspace may see it.
type ContainerHealth struct {
	InstanceID string
	Name       string
	Healthy    bool
	Status     string
}

// ContainersHealth is GET /health/containers: the runtime's report of each
// instance the workspace sees; a report is never a failure of the request.
func (s *Service) ContainersHealth(ctx context.Context, c authn.Caller) ([]ContainerHealth, error) {
	rows, _, err := s.listInstances(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]ContainerHealth, len(rows))
	var wg sync.WaitGroup
	for i, r := range rows {
		wg.Add(1)
		go func() {
			defer wg.Done()
			row := ContainerHealth{InstanceID: r.ID, Name: r.Name}
			h, err := s.d.Runtime.Health(ctx, r.ID)
			switch {
			case errors.Is(err, ErrRuntimeNotRunning):
				row.Status = "not_running"
			case err != nil:
				s.d.Log.ErrorContext(ctx, "MCP runtime health read failed", "instance_id", r.ID, "error", err)
				row.Status = "error"
			default:
				row.Healthy, row.Status = h.Healthy, h.Status
				if row.Status == "" {
					row.Status = "unhealthy"
					if h.Healthy {
						row.Status = "healthy"
					}
				}
			}
			out[i] = row
		}()
	}
	wg.Wait()
	return out, nil
}

// CheckResult is POST /check's answer.
type CheckResult struct {
	Valid   bool
	Message string
	Details map[string]any
}

// CheckConfiguration is POST /check: the runtime's dry-run validation of a
// spec; a runtime it cannot reach is 503.
func (s *Service) CheckConfiguration(ctx context.Context, jsonSpec any) (CheckResult, error) {
	spec, ok := jsonSpec.(map[string]any)
	if !ok {
		return CheckResult{Message: "Configuration validation failed: json_spec must be an object"}, nil
	}
	v, err := s.d.Runtime.Validate(ctx, "validation-test", spec)
	if err != nil {
		s.d.Log.WarnContext(ctx, "MCP runtime validation unreachable", "error", err)
		return CheckResult{}, &domain.Unavailable{Msg: "Unable to connect to container manager for validation"}
	}
	if !v.Valid {
		return CheckResult{Message: "Configuration validation failed: " + v.Message}, nil
	}
	return CheckResult{Valid: true, Message: "Configuration is valid", Details: v.Details}, nil
}
