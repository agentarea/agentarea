package app

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	runsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// runsProviders are the modules runs' surface reads. Models and Sandbox serve
// only its HTTP routes; a role without them leaves those parts unwired.
type runsProviders struct {
	Agents     *agents.Module
	Governance *governance.Module
	Models     *models.Module
	Sandbox    *sandbox.Module
}

// newRunsSurface is runs' task creation and task reads, and with an edge its
// HTTP surface, as the serve and events roles build them.
func newRunsSurface(e *edge, d coreDeps, p runsProviders) *runs.Surface {
	sd := runs.SurfaceDeps{Durable: d.Durable, Audit: p.Governance.Audit(),
		AgentQueue: func() string {
			if d.Durable == nil {
				return ""
			}
			return d.Durable.Config.Queues.Agent
		},
		Service: runsservice.SurfaceDeps{DB: d.DB, Broker: d.Broker, Agents: p.Agents.Lookup(), Definitions: p.Agents.Definitions(), Secrets: d.Secrets.Manager, Currency: func() string { return string(d.Extensions.CustomerPricing.Currency()) }, AppURL: d.AppURL, Log: d.Log,
			AuditReader: p.Governance.AuditReader(), Policies: p.Governance.RunPolicies(),
			Permissions: func(ctx context.Context, c authn.Caller, permission, resourceType, resourceID string) error {
				return authz.NewPermissions(d.Graph, d.Log).Require(ctx, c, permission, resourceType, resourceID)
			},
			WebhookURL: func(ctx context.Context, rawURL string) error {
				_, err := d.Outbound.Guard().CheckURL(ctx, rawURL)
				return err
			},
		}}
	if e != nil {
		sd.Workspace, sd.Service.Admin = e.Workspace, e.Admin
	}
	if p.Models != nil {
		sd.Service.Models = p.Models.Resolver()
	}
	if p.Sandbox != nil {
		sd.Service.Files, sd.Service.Workspaces, sd.Service.TaskFiles = p.Sandbox.Files(), p.Sandbox.TaskWorkspace(), p.Sandbox.TaskFiles()
	}
	return runs.NewSurface(sd)
}

// streamsRunsPorts are the streams ports runs and agents answer: agent
// standing, task creation, task reads and the reads a firing needs.
func streamsRunsPorts(sd *streams.Deps, r *runs.Surface, a *agents.Module) {
	sd.Agents = streamsAgents{a.Standing()}
	sd.Tasks = r.Tasks()
	sd.TaskReads = streamsTaskReads{r.TaskReads()}
	sd.FiringTasks = streamsFiringTasks{tasks: r.FiringTasks(), saved: a.Standing()}
	sd.TaskOutcomes = r.TaskOutcomes()
}

// streamsAgents answers streams' "the agent exists and is not archived".
type streamsAgents struct{ s agentsapi.Standing }

func (a streamsAgents) AgentExists(ctx context.Context, ws scope.Workspace, id string) (bool, error) {
	status, ok, err := a.s.AgentStatus(ctx, ws, id)
	return ok && status != agentsapi.StatusArchived, err
}

type streamsTaskReads struct{ r runsapi.TaskReads }

func (t streamsTaskReads) Statuses(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	return t.r.Statuses(ctx, ws, ids)
}

func (t streamsTaskReads) Costs(ctx context.Context, ws scope.Workspace, ids []string) (map[string]streamsapi.TaskCost, error) {
	got, err := t.r.Costs(ctx, ws, ids)
	if err != nil {
		return nil, err
	}
	out := make(map[string]streamsapi.TaskCost, len(got))
	for id, v := range got {
		out[id] = streamsapi.TaskCost{CostUSD: &v}
	}
	return out, nil
}

type streamsFiringTasks struct {
	tasks runsapi.FiringTasks
	saved agentsapi.Standing
}

func (f streamsFiringTasks) Task(ctx context.Context, ws scope.Workspace, id string) (streamsapi.StoredTask, bool, error) {
	t, ok, err := f.tasks.Task(ctx, ws, id)
	return streamsapi.StoredTask{Status: t.Status, ExecutionID: t.ExecutionID}, ok, err
}

func (f streamsFiringTasks) RestartUndispatched(ctx context.Context, ws scope.Workspace, id, message string) error {
	return f.tasks.RestartUndispatched(ctx, ws, id, message)
}

func (f streamsFiringTasks) OpenRunFrom(ctx context.Context, ws scope.Workspace, originType, originID string) (string, error) {
	return f.tasks.OpenRunFrom(ctx, ws, originType, originID)
}

func (f streamsFiringTasks) Definition(ctx context.Context, ws scope.Workspace, id string) (streamsapi.TaskDefinition, bool, error) {
	d, ok, err := f.saved.TaskDefinition(ctx, ws, id)
	if err != nil || !ok {
		return streamsapi.TaskDefinition{}, false, err
	}
	var params map[string]any
	if json.Unmarshal(d.Parameters, &params) != nil || params == nil {
		params = map[string]any{}
	}
	return streamsapi.TaskDefinition{Description: d.Description, Parameters: params}, true, nil
}

func (f streamsFiringTasks) Origin(ctx context.Context, ws scope.Workspace, taskID string) (streamsapi.TaskOrigin, bool, error) {
	o, ok, err := f.tasks.Origin(ctx, ws, taskID)
	return streamsapi.TaskOrigin{OriginType: o.OriginType, OriginID: o.OriginID, CausationID: o.CausationID}, ok, err
}
