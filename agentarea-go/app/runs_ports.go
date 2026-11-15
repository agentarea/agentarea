package app

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	kscope "github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	projectsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	runsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	streamsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

// mcpCaller runs a run's MCP tool calls through connections (connections
// PORTING-NOTES "Runs adapter"); a failed call is a result, not an error.
type mcpCaller struct{ t connectionsapi.MCPTools }

func (c mcpCaller) Call(ctx context.Context, inv runsservice.ToolInvocation) (runsservice.ToolOutput, error) {
	b := inv.Binding.MCP
	if b == nil {
		return runsservice.ToolOutput{}, fmt.Errorf("tool %s is bound to mcp without an instance", inv.ToolName)
	}
	call := connectionsapi.MCPCall{
		WorkspaceID: inv.Principal.WorkspaceID, UserID: inv.Principal.UserID, AgentID: inv.Principal.AgentID,
		TaskID: inv.TaskID, ToolCallID: inv.ToolCallID, InstanceID: b.InstanceID, Tool: b.RawName,
		Args: inv.Args, TaskMetadata: inv.RunMetadata, Paid: paidCall(inv),
	}
	if call.Tool == "" {
		call.Tool = inv.ToolName
	}
	if inv.Progress != nil {
		call.Progress = func(progress float64, total *float64, message string) {
			inv.Progress(runsservice.ToolProgress{Progress: progress, Total: total, Message: message})
		}
	}
	r, err := c.t.Call(ctx, call)
	if err != nil {
		return runsservice.ToolOutput{}, err
	}
	out := runsservice.ToolOutput{
		Success: r.Success, Result: r.Result, Error: r.Error, Source: "mcp",
		ServerInstanceID: r.ServerInstanceID, ServerName: b.ServerName, ServerIcon: b.ServerIcon, MCPAppTool: b.OpensApp,
		StructuredContent: r.StructuredContent, StructuredContentDropped: r.StructuredContentDropped, MeteredMeta: r.Meta,
	}
	out.Payments, out.ServiceCost = toolPayments(r.Payments)
	for _, img := range r.Images {
		out.Images = append(out.Images, runsservice.ToolImage{Data: []byte(img.Data), MimeType: img.MimeType})
	}
	return out, nil
}

// openAPICaller runs a run's OpenAPI operation calls through connections.
type openAPICaller struct{ t connectionsapi.OpenAPITools }

func (c openAPICaller) Call(ctx context.Context, inv runsservice.ToolInvocation) (runsservice.ToolOutput, error) {
	b := inv.Binding.OpenAPI
	if b == nil {
		return runsservice.ToolOutput{}, fmt.Errorf("tool %s is bound to openapi without a connection", inv.ToolName)
	}
	ws, err := kscope.NewWorkspace(inv.Principal.WorkspaceID, "")
	if err != nil {
		return runsservice.ToolOutput{}, err
	}
	op := b.OperationID
	if op == "" {
		op = inv.ToolName
	}
	r := c.t.CallOpenAPI(ctx, ws, connectionsapi.OpenAPICall{UserID: inv.Principal.UserID, AgentID: inv.Principal.AgentID, ConnectionID: b.ConnectionID,
		Operation: op, Args: inv.Args, ToolCallID: inv.ToolCallID, Paid: paidCall(inv)})
	out := runsservice.ToolOutput{Success: r.Success, Result: r.Result, Error: r.Error, Source: "openapi", MeteredBody: r.Body}
	out.Payments, out.ServiceCost = toolPayments(r.Payments)
	return out, nil
}

// paidCall keys the call's wallet payments; the budget period is the
// execution, else the task (get_payment_context).
func paidCall(inv runsservice.ToolInvocation) connectionsapi.PaidCall {
	exec := inv.ExecutionID
	if exec == "" {
		exec = inv.TaskID
	}
	return connectionsapi.PaidCall{ExecutionID: exec, CallRef: inv.CallRef}
}

// toolPayments are the call's wallet payments for the meter, and what the
// settled ones cost.
func toolPayments(ps []connectionsapi.Payment) ([]runsservice.Payment, money.Decimal) {
	var out []runsservice.Payment
	cost := money.Zero()
	for _, p := range ps {
		out = append(out, runsservice.Payment{Protocol: p.Protocol, Amount: p.Amount, Currency: "USD", Network: p.Network,
			Recipient: p.Recipient, TxHash: p.TxHash, IdempotencyKey: p.IdempotencyKey, Settled: p.Settled, AlreadySettled: p.AlreadySettled})
		if p.Settled {
			cost = cost.Add(p.Amount)
		}
	}
	return out, cost
}

// notFound maps streams' gone trigger to the runs port's ErrNotFound.
func notFound(err error) error {
	if errors.Is(err, domain.ErrNotFound) {
		return fmt.Errorf("%w: %w", runsservice.ErrNotFound, err)
	}
	return err
}

// streamsTriggers is runs' service.Triggers over streams' scheduling side.
type streamsTriggers struct{ s *streamsservice.Scheduling }

func cronTrigger(r streamsapi.CronRow) runsservice.CronTrigger {
	return runsservice.CronTrigger{ID: r.ID, CronExpression: r.CronExpression, TimeZone: r.TimeZone, Active: r.Active}
}

func (t streamsTriggers) CronTriggers(ctx context.Context) ([]runsservice.CronTrigger, error) {
	rows, err := t.s.CronTriggers(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]runsservice.CronTrigger, len(rows))
	for i, r := range rows {
		out[i] = cronTrigger(r)
	}
	return out, nil
}

func (t streamsTriggers) CronTrigger(ctx context.Context, id string) (runsservice.CronTrigger, bool, error) {
	r, ok, err := t.s.CronTrigger(ctx, id)
	return cronTrigger(r), ok, err
}

func (t streamsTriggers) Trigger(ctx context.Context, id string) (runsservice.TriggerState, error) {
	s, err := t.s.Trigger(ctx, id)
	if err != nil {
		return runsservice.TriggerState{}, notFound(err)
	}
	return runsservice.TriggerState{ID: s.ID, Name: s.Name, WorkspaceID: s.WorkspaceID, Active: s.Active}, nil
}

func (t streamsTriggers) EvaluateConditions(ctx context.Context, id string, eventData map[string]any) (bool, error) {
	return t.s.EvaluateConditions(ctx, id, eventData)
}

func (t streamsTriggers) Fire(ctx context.Context, f runsservice.TriggerFire) (runsservice.TriggerFiring, error) {
	r, err := t.s.Fire(ctx, streamsapi.TriggerFire{TriggerID: f.TriggerID, Data: f.Data, TaskID: f.TaskID,
		OriginType: f.Provenance.OriginType, OriginID: f.Provenance.OriginID, CorrelationID: f.Provenance.CorrelationID})
	if err != nil {
		return runsservice.TriggerFiring{}, notFound(err)
	}
	return runsservice.TriggerFiring{Outcome: r.Outcome, Reason: r.Reason, TaskID: r.TaskID, ExecutionID: r.ExecutionID,
		BlockedBy: r.BlockedBy, Verdict: r.Verdict}, nil
}

func (t streamsTriggers) RecordExecution(ctx context.Context, id string, r runsservice.TriggerExecutionRecord) (runsservice.RecordedTriggerExecution, error) {
	got, err := t.s.RecordExecution(ctx, id, streamsapi.ExecutionRecord{Status: r.Status, ExecutionTime: r.ExecutionTime,
		TaskID: r.TaskID, ErrorMessage: r.ErrorMessage, TriggerData: r.TriggerData})
	if err != nil {
		return runsservice.RecordedTriggerExecution{}, notFound(err)
	}
	return runsservice.RecordedTriggerExecution{ID: got.ID, ExecutedAt: got.ExecutedAt}, nil
}

// streamsBatches is runs' service.TriggerBatches over streams.
type streamsBatches struct{ s *streamsservice.Scheduling }

func triggerBatch(b runsservice.TriggerBatch) streamsapi.TriggerBatch {
	return streamsapi.TriggerBatch{TriggerID: b.TriggerID, SubscriptionID: b.SubscriptionID, WorkspaceID: b.WorkspaceID,
		ConfiguredBy: b.ConfiguredBy, Caller: b.Caller, WorkflowID: b.WorkflowID, EventIDs: b.EventIDs, Reason: b.Reason}
}

func (t streamsBatches) Fire(ctx context.Context, b runsservice.TriggerBatch) (int, error) {
	return t.s.FireBatch(ctx, triggerBatch(b))
}

func (t streamsBatches) Close(ctx context.Context, b runsservice.TriggerBatch) (int, error) {
	return t.s.CloseBatch(ctx, triggerBatch(b))
}

// runTools is RunDefinitions.Tools over connections' run tool resolution.
type runTools struct{ t connectionsapi.RunTools }

func (r runTools) Tools(ctx context.Context, p runsservice.Principal, req runsservice.ToolsRequest) (runsservice.ToolSet, error) {
	ts, err := r.t.RunTools(ctx, connectionsapi.RunToolsRequest{WorkspaceID: p.WorkspaceID, UserID: p.UserID, AgentID: p.AgentID,
		TaskID: req.TaskID, Agent: req.Agent, MCPInstanceIDs: req.MCPInstanceIDs})
	switch {
	case errors.Is(err, connectionsapi.ErrToolsNotFound):
		err = errors.Join(runsservice.ErrNotFound, err)
	case errors.Is(err, connectionsapi.ErrToolsRefused):
		err = errors.Join(runsservice.ErrRefused, err)
	}
	return runsservice.ToolSet(ts), err
}

// runSkills, runInstructions and runInputs are the other reads of
// RunDefinitions, answered by agents, projects and sandbox.
type (
	runSkills interface {
		Skills(ctx context.Context, p runsservice.Principal, agent runsapi.AgentSpec, skillIDs []string) ([]runsapi.Skill, []runsapi.WithheldSkill, error)
	}
	runInstructions interface {
		ProjectInstructions(ctx context.Context, p runsservice.Principal, projectID string) ([]string, error)
	}
	runInputs interface {
		Inputs(ctx context.Context, p runsservice.Principal, req runsservice.InputsRequest) ([]runsapi.InputFile, error)
	}
)

// runDefinitions is runs' RunDefinitions over its four owners.
type runDefinitions struct {
	runTools
	runSkills
	runInstructions
	runInputs
}

// newRunDefinitions is nil until every owner answers its part, so the worker
// names the port missing instead of failing a run.
func newRunDefinitions(tools runTools, skills runSkills, instructions runInstructions, inputs runInputs) runsservice.RunDefinitions {
	if tools.t == nil || skills == nil || instructions == nil || inputs == nil {
		return nil
	}
	return runDefinitions{tools, skills, instructions, inputs}
}

func runsWorkspace(p runsservice.Principal) (kscope.Workspace, error) {
	return kscope.NewWorkspace(p.WorkspaceID, "")
}

func runsSkillErr(err error) error {
	var u *agentsapi.SkillUnreachableError
	switch {
	case errors.Is(err, agentsapi.ErrSkillNotFound), errors.Is(err, agentsapi.ErrNotFound):
		return errors.Join(runsservice.ErrNotFound, err)
	case errors.Is(err, agentsapi.ErrSkillRefused):
		return errors.Join(runsservice.ErrRefused, err)
	case errors.As(err, &u):
		return &runsservice.UnreachableError{Service: u.Service, Err: u.Err}
	}
	return err
}

// runSkillsPort is RunDefinitions.Skills over agents.
type runSkillsPort struct{ s agentsapi.RunSkills }

func (r runSkillsPort) Skills(ctx context.Context, p runsservice.Principal, agent runsapi.AgentSpec, ids []string) ([]runsapi.Skill, []runsapi.WithheldSkill, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return nil, nil, err
	}
	s, w, err := r.s.Offered(ctx, ws, agent.ID, ids)
	return s, w, runsSkillErr(err)
}

// skillPackages is runs' SkillPackages over agents.
type skillPackages struct{ s agentsapi.RunSkills }

func (k skillPackages) Allow(ctx context.Context, p runsservice.Principal, sk runsapi.Skill) error {
	ws, err := runsWorkspace(p)
	if err != nil {
		return err
	}
	return runsSkillErr(k.s.Allow(ctx, ws, sk))
}

func (k skillPackages) ReadSkillMD(ctx context.Context, p runsservice.Principal, sk runsapi.Skill) (string, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return "", err
	}
	body, err := k.s.ReadSkillMD(ctx, ws, sk)
	return body, runsSkillErr(err)
}

func (k skillPackages) Files(ctx context.Context, p runsservice.Principal, sk runsapi.Skill) ([]runsservice.SkillFile, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return nil, err
	}
	files, err := k.s.PackageFiles(ctx, ws, sk)
	if err != nil {
		return nil, runsSkillErr(err)
	}
	out := make([]runsservice.SkillFile, len(files))
	for i, f := range files {
		out[i] = runsservice.SkillFile(f)
	}
	return out, nil
}

// runInstructionsPort is RunDefinitions.ProjectInstructions over projects.
type runInstructionsPort struct{ p projectsapi.RunInstructions }

func (r runInstructionsPort) ProjectInstructions(ctx context.Context, p runsservice.Principal, projectID string) ([]string, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return nil, err
	}
	out, err := r.p.Blocks(ctx, ws, p.AgentID, projectID)
	if errors.Is(err, projectsapi.ErrInvalidProject) {
		err = errors.Join(runsservice.ErrNotFound, err)
	}
	return out, err
}

// runInputsPort is RunDefinitions.Inputs over sandbox.
type runInputsPort struct{ i sandboxapi.RunInputs }

func (r runInputsPort) Inputs(ctx context.Context, p runsservice.Principal, req runsservice.InputsRequest) ([]runsapi.InputFile, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return nil, err
	}
	in, err := r.i.Prepare(ctx, ws, sandboxapi.RunInputsRequest{TaskID: req.TaskID, UserID: p.UserID, Paths: req.FileIDs,
		TriggerEvent: req.TriggerEvent, TriggerEventFileName: req.TriggerEventFileName})
	if errors.Is(err, sandboxapi.ErrInputRefused) {
		return nil, errors.Join(runsservice.ErrRefused, err)
	}
	if err != nil {
		return nil, err
	}
	out := make([]runsapi.InputFile, len(in))
	for i, f := range in {
		out[i] = runsapi.InputFile{Path: f.Path, Kind: f.Kind, SHA256: f.SHA256, Size: f.Size}
	}
	return out, nil
}

// processorRunner is streams' ProcessorRunner over the sandbox.
type processorRunner struct{ p sandboxapi.Processors }

func (r processorRunner) Run(ctx context.Context, ws, session, command string, timeout time.Duration, max int) (streamsservice.CodeRun, error) {
	run, err := r.p.Run(ctx, ws, session, command, timeout, max)
	if err != nil {
		return streamsservice.CodeRun{}, errors.Join(streamsservice.ErrProcessorRuntimeUnavailable, err)
	}
	return streamsservice.CodeRun(run), nil
}
