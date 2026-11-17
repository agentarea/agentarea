package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

// SurfaceDeps are what the runs HTTP surface needs (api/v1/agents_tasks.py,
// inbox.py, tool_call_approvals.py).
type SurfaceDeps struct {
	DB          db.Database
	Executor    durable.Executor
	Broker      events.Broker
	Agents      agentsapi.Lookup
	Definitions agentsapi.Definitions
	// Admin is nil for a workspace admin and authz.ErrNotWorkspaceAdmin otherwise.
	Admin func(ctx context.Context) error
	// Secrets is the workspace secret manager a person's input answers go to.
	Secrets func(s db.Session, userID string) secrets.Manager
	// Currency is the billing currency of the spend ledger.
	Currency func() string
	// AppURL is AGENTAREA_APP_URL.
	AppURL string
	// Policies resolves a started run's policy; Launcher starts its workflow;
	// Permissions answers requires(permission, type); nil leaves the create
	// and resume routes unmounted.
	Policies    governanceapi.RunPolicies
	Launcher    RunLauncher
	Resumer     RunResumer
	Permissions func(ctx context.Context, c authn.Caller, permission, resourceType, resourceID string) error
	// WebhookURL refuses a webhook URL the outbound policy does not admit.
	WebhookURL func(ctx context.Context, rawURL string) error
	// Files and Workspaces stage attachments; TaskFiles reads a task's
	// artifacts and live files; Models resolves change_model's instance.
	Files      sandboxapi.Files
	Workspaces sandboxapi.TaskWorkspace
	TaskFiles  sandboxapi.TaskFiles
	Models     modelsapi.Resolver
	// AuditReader reads the approval decisions (governance); nil leaves them unmounted.
	AuditReader governanceapi.AuditReader
	// ToolHints reads an MCP tool's safety hint (connections); nil answers every hint null.
	ToolHints ToolHints
	// Counter counts runs a spend cap refused for usage analytics; nil counts nothing.
	Counter analytics.Counter
	Now     func() time.Time
	Log     *slog.Logger
}

// Surface serves the runs routes.
type Surface struct {
	d   SurfaceDeps
	hub *taskHub
}

// NewSurface builds the surface.
func NewSurface(d SurfaceDeps) *Surface {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	return &Surface{d: d, hub: newTaskHub(d.Broker, d.Log)}
}

// endedStatuses is ENDED_TASK_STATUSES.
func endedStatuses(s string) bool {
	switch s {
	case "blocked", "completed", "failed", "cancelled":
		return true
	}
	return false
}

// finishedWorkflowStates is _FINISHED_WORKFLOW_STATES.
func finishedWorkflowStates(s string) bool {
	switch s {
	case "completed", "failed", "cancelled", "terminated":
		return true
	}
	return false
}

// Provenance is TaskProvenance.
type Provenance struct {
	OriginType, OriginID, CorrelationID, CausationID, ParentTaskID, TaskDefinitionID, SourceIdentity *string
	Depth                                                                                            int
}

// Task is a task row as the API reads it (Task after _orm_to_domain).
type Task struct {
	ID, AgentID, Description, Status, CreatedBy string
	Parameters                                  wirejson.Object
	// Result is nil or an object; any other stored value is {"response": value}.
	Result                              any
	Error                               *string
	ExecutionID                         *string
	StartedAt, CompletedAt, ScheduledAt *time.Time
	Metadata                            wirejson.Object
	CreatedAt, UpdatedAt                time.Time
	Provenance                          Provenance
}

func objectOf(raw string) wirejson.Object {
	if raw == "" {
		return wirejson.Object{}
	}
	v, err := wirejson.Unmarshal([]byte(raw))
	if err != nil {
		return wirejson.Object{}
	}
	if o, ok := v.(wirejson.Object); ok {
		return o
	}
	return wirejson.Object{}
}

func resultOf(raw string) (any, error) {
	if raw == "" {
		return nil, nil
	}
	v, err := wirejson.Unmarshal([]byte(raw))
	if err != nil {
		return nil, fmt.Errorf("task result: %w", err)
	}
	switch v := v.(type) {
	case nil:
		return nil, nil
	case wirejson.Object:
		return v, nil
	default:
		return wirejson.Object{{Key: "response", Value: v}}, nil
	}
}

func uuidPtr(u uuid.NullUUID) *string {
	if !u.Valid {
		return nil
	}
	s := u.UUID.String()
	return &s
}

func taskOf(r store.SurfaceTaskRow) (Task, error) {
	result, err := resultOf(r.Result)
	if err != nil {
		return Task{}, err
	}
	t := Task{
		ID: r.ID.String(), AgentID: r.AgentID.String(), Description: r.Description, Status: r.Status,
		CreatedBy: r.CreatedBy, Parameters: objectOf(r.Parameters), Result: result, Error: store.TextPtr(r.Error),
		ExecutionID: store.TextPtr(r.ExecutionID), StartedAt: store.TimestampPtr(r.StartedAt), CompletedAt: store.TimestampPtr(r.CompletedAt),
		ScheduledAt: store.TimestamptzPtr(r.ScheduledAt), Metadata: objectOf(r.TaskMetadata),
		Provenance: Provenance{
			OriginType: store.TextPtr(r.OriginType), OriginID: store.TextPtr(r.OriginID), CorrelationID: store.TextPtr(r.CorrelationID),
			CausationID: store.TextPtr(r.CausationID), ParentTaskID: uuidPtr(r.ParentTaskID), Depth: int(r.Depth),
			TaskDefinitionID: uuidPtr(r.TaskDefinitionID), SourceIdentity: store.TextPtr(r.SourceIdentity),
		},
	}
	if r.CreatedAt.Valid {
		t.CreatedAt = r.CreatedAt.Time.UTC()
	}
	if r.UpdatedAt.Valid {
		t.UpdatedAt = r.UpdatedAt.Time.UTC()
	}
	return t, nil
}

// executionID is task_execution_id: the stored execution id, else task-<id>.
func (t Task) executionID() string {
	if t.ExecutionID != nil && *t.ExecutionID != "" {
		return *t.ExecutionID
	}
	return "task-" + t.ID
}

// PyISO is a datetime's isoformat in UTC: utc_isoformat with z, else "+00:00".
func PyISO(t time.Time, z bool) string {
	t = t.UTC()
	s := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += fmt.Sprintf(".%06d", us)
	}
	if z {
		return s + "Z"
	}
	return s + "+00:00"
}

func isoOrNil(t *time.Time) any {
	if t == nil {
		return nil
	}
	return PyISO(*t, true)
}

func strOrNil(p *string) any {
	if p == nil {
		return nil
	}
	return *p
}

func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// internal is the HTTPException(500, "Internal server error") a route raises
// for an error it did not expect, after logging it.
func (s *Surface) internal(ctx context.Context, msg string, err error) error {
	s.d.Log.ErrorContext(ctx, msg, "error", err.Error())
	return httpx.HTTPError(http.StatusInternalServerError, "Internal server error").Wrap(err)
}

func notFound(detail string) error { return httpx.HTTPError(http.StatusNotFound, detail) }

func parseID(id string) (uuid.UUID, bool) {
	u, err := uuid.Parse(id)
	return u, err == nil
}

// loadTask reads a task of the caller's workspace; ok false when there is none.
func (s *Surface) loadTask(ctx context.Context, ws scope.Workspace, taskID string) (Task, bool, error) {
	id, ok := parseID(taskID)
	if !ok {
		return Task{}, false, nil
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return Task{}, false, err
	}
	defer release()
	row, err := store.New(sess.Q()).SurfaceTask(ctx, store.SurfaceTaskParams{ID: id, WorkspaceID: ws.ID()})
	if store.NoRows(err) {
		return Task{}, false, nil
	}
	if err != nil {
		return Task{}, false, err
	}
	t, err := taskOf(row)
	return t, err == nil, err
}

// taskOfAgent is _verify_task_for_agent: 404 "Task not found" unless the task is the agent's.
func (s *Surface) taskOfAgent(ctx context.Context, ws scope.Workspace, agentID, taskID string) (Task, error) {
	t, ok, err := s.loadTask(ctx, ws, taskID)
	if err != nil {
		return Task{}, err
	}
	if !ok || t.AgentID != agentID {
		return Task{}, notFound("Task not found")
	}
	return t, nil
}

// requireAgent is agent_service.get: 404 "Agent not found".
func (s *Surface) requireAgent(ctx context.Context, ws scope.Workspace, agentID string) error {
	ok, err := s.d.Agents.AgentExists(ctx, ws, agentID)
	if err != nil {
		return err
	}
	if !ok {
		return notFound("Agent not found")
	}
	return nil
}

// mayAct is caller_may_act_on_task: the run's creator, or a workspace admin.
func (s *Surface) mayAct(ctx context.Context, c authn.Caller, t Task) (bool, error) {
	if t.CreatedBy != "" && t.CreatedBy == c.UserID {
		return true, nil
	}
	err := s.d.Admin(ctx)
	if err == nil {
		return true, nil
	}
	if errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		return false, nil
	}
	return false, err
}

// humanOnly refuses an agent what only a person may do on a run: decide a
// held call, answer a question, grant it more to spend.
const humanOnly = "Only a person may do this; an agent acting in a run may not"

func refuseAgentHTTP(c authn.Caller) error {
	if c.ActsAsAgent() {
		return httpx.HTTPError(http.StatusForbidden, humanOnly)
	}
	return nil
}

// RequireTaskAuthority is requires_task_authority: a task that does not
// exist passes, so the handler answers its own 404.
func (s *Surface) RequireTaskAuthority(ctx context.Context, taskID string) error {
	c, err := caller(ctx)
	if err != nil {
		return err
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil || !ok {
		return err
	}
	if t.CreatedBy != "" && t.CreatedBy == c.UserID {
		return nil
	}
	return s.d.Admin(ctx)
}

// apiCaller is _is_api_caller: an API key or a service client.
func apiCaller(c authn.Caller) bool {
	return (c.Credential != nil && c.Credential.Kind == authn.KindAPIKey) || c.ClientID != ""
}

func truthy(v any) bool {
	switch v := v.(type) {
	case nil:
		return false
	case bool:
		return v
	case string:
		return v != ""
	case json.Number:
		f, err := v.Float64()
		return err != nil || f != 0
	case wirejson.Float:
		return v != 0
	case wirejson.Object:
		return len(v) > 0
	case []any:
		return len(v) > 0
	}
	return true
}

// pyStr is str(v) for a JSON value.
func pyStr(v any) string {
	switch v := v.(type) {
	case string:
		return v
	case bool:
		if v {
			return "True"
		}
		return "False"
	case nil:
		return "None"
	case json.Number:
		return v.String()
	case wirejson.Float:
		return wirejson.FormatFloat(float64(v))
	}
	b, err := wirejson.Marshal(v, wirejson.Dumps)
	if err != nil {
		return fmt.Sprint(v)
	}
	return string(b)
}

func getObj(v any, key string) (any, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		return nil, false
	}
	return o.Get(key)
}

// failureReason is _failure_reason_from_result.
func failureReason(result any, metadata wirejson.Object) any {
	for _, src := range []any{metadata, result} {
		if v, ok := getObj(src, "failure_reason"); ok && truthy(v) {
			return pyStr(v)
		}
	}
	return nil
}

// asFloat is pydantic's float coercion of a stored number.
func asFloat(v any) (any, bool) {
	switch v := v.(type) {
	case json.Number:
		f, err := strconv.ParseFloat(v.String(), 64)
		return wirejson.Float(f), err == nil
	case wirejson.Float:
		return v, true
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
		return wirejson.Float(f), err == nil
	case bool:
		if v {
			return wirejson.Float(1), true
		}
		return wirejson.Float(0), true
	}
	return nil, false
}

// usageFields is _usage_fields: total_cost and total_tokens as the result stored them.
func usageFields(result any) (cost, tokens any) {
	if v, ok := getObj(result, "total_cost"); ok && v != nil {
		if f, ok := asFloat(v); ok {
			cost = f
		}
	}
	if v, ok := getObj(result, "tokens_used"); ok {
		if n, isNum := v.(json.Number); isNum {
			if _, err := n.Int64(); err == nil {
				tokens = n
			}
		}
	}
	return cost, tokens
}

// callerFields is _caller_fields: end_user_id and metadata for an API caller only.
func callerFields(t Task, c authn.Caller) (endUser, metadata any) {
	if !apiCaller(c) {
		return nil, nil
	}
	endUser, _ = t.Metadata.Get("end_user_id")
	metadata, _ = t.Metadata.Get("app_metadata")
	return endUser, metadata
}

func provenanceJSON(p Provenance) wirejson.Object {
	return wirejson.Object{
		{Key: "origin_type", Value: strOrNil(p.OriginType)},
		{Key: "origin_id", Value: strOrNil(p.OriginID)},
		{Key: "correlation_id", Value: strOrNil(p.CorrelationID)},
		{Key: "causation_id", Value: strOrNil(p.CausationID)},
		{Key: "parent_task_id", Value: strOrNil(p.ParentTaskID)},
		{Key: "depth", Value: p.Depth},
		{Key: "task_definition_id", Value: strOrNil(p.TaskDefinitionID)},
		{Key: "source_identity", Value: strOrNil(p.SourceIdentity)},
	}
}

// TaskResponseJSON is TaskResponse.from_agent_task in its field order.
func TaskResponseJSON(t Task, c authn.Caller) wirejson.Object {
	cost, tokens := usageFields(t.Result)
	endUser, meta := callerFields(t, c)
	return wirejson.Object{
		{Key: "id", Value: t.ID},
		{Key: "agent_id", Value: t.AgentID},
		{Key: "description", Value: t.Description},
		{Key: "parameters", Value: t.Parameters},
		{Key: "status", Value: t.Status},
		{Key: "result", Value: t.Result},
		{Key: "error", Value: strOrNil(t.Error)},
		{Key: "failure_reason", Value: failureReason(t.Result, t.Metadata)},
		{Key: "created_at", Value: PyISO(t.CreatedAt, true)},
		{Key: "execution_id", Value: strOrNil(t.ExecutionID)},
		{Key: "total_cost", Value: cost},
		{Key: "total_tokens", Value: tokens},
		{Key: "end_user_id", Value: endUser},
		{Key: "metadata", Value: meta},
		{Key: "scheduled_at", Value: isoOrNil(t.ScheduledAt)},
		{Key: "created_by", Value: t.CreatedBy},
		{Key: "provenance", Value: provenanceJSON(t.Provenance)},
	}
}

// TaskWithAgentJSON is TaskWithAgent in its field order.
func TaskWithAgentJSON(t Task, c authn.Caller, agentName, escalationID, escalationTool any) wirejson.Object {
	r := TaskResponseJSON(t, c)
	out := make(wirejson.Object, 0, len(r)+3)
	for _, m := range r {
		switch m.Key {
		case "agent_id":
			out = append(out, m, wirejson.Member{Key: "agent_name", Value: agentName})
		case "created_by":
			out = append(out, wirejson.Member{Key: "escalation_id", Value: escalationID},
				wirejson.Member{Key: "escalation_tool_name", Value: escalationTool}, m)
		default:
			out = append(out, m)
		}
	}
	return out
}
