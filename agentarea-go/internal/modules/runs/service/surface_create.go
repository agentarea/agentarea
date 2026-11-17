package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"path"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

// Refusal is why a run was not started: the HTTP answer of the sync and
// schedule routes, the error frame (Type) of the streaming one.
type Refusal struct {
	Status int
	Code   string
	Detail string
	Type   string
	Extra  wirejson.Object
	cause  error
}

func (r *Refusal) Error() string { return r.Detail }
func (r *Refusal) Unwrap() error { return r.cause }

// HTTP is the problem the sync and schedule routes answer with.
func (r *Refusal) HTTP() *httpx.Error {
	e := httpx.NewError(r.Status, r.Code, r.Detail)
	for _, m := range r.Extra {
		e = e.With(m.Key, m.Value)
	}
	return e.Wrap(r)
}

func refused(status int, code, detail, typ string, cause error) *Refusal {
	return &Refusal{Status: status, Code: code, Detail: detail, Type: typ, cause: cause}
}

// Webhook is the caller's delivery target; Secret is write-only.
type Webhook struct {
	URL    string
	Secret *string
}

// CreateRequest is TaskCreate (and ScheduleTaskCreate) after validation.
type CreateRequest struct {
	AgentID               string
	Description           string
	Parameters            map[string]any
	ExecutionTurns        *int64
	RequiresHumanApproval bool
	ProjectID             *string
	TaskPolicy            *governanceapi.Policy
	Attachments           []string
	AppMetadata           any
	EndUserID             *string
	Webhook               *Webhook
	ScheduledAt           *time.Time
}

// CreateMounted is whether the ports starting a run are wired.
func (s *Surface) CreateMounted() bool {
	return s.d.Policies != nil && s.d.Launcher != nil && s.d.Permissions != nil
}

// RequireExecute is requires("execute", "agent"): the caller may invoke the agent.
func (s *Surface) RequireExecute(ctx context.Context, agentID string) error {
	c, err := caller(ctx)
	if err != nil {
		return err
	}
	return s.d.Permissions(ctx, c, "execute", "agent", agentID)
}

const (
	appMetadataKey = "app_metadata"
	endUserIDKey   = "end_user_id"
	webhookKey     = "task_webhook"
	runnerKey      = "runner_client_id"
)

// trustedMetadata is TaskCreate.trusted_metadata: only an API caller sets it.
func (s *Surface) trustedMetadata(ctx context.Context, c authn.Caller, req CreateRequest) (map[string]any, error) {
	if req.AppMetadata == nil && req.EndUserID == nil && req.Webhook == nil {
		return map[string]any{}, nil
	}
	if !apiCaller(c) {
		return nil, httpx.HTTPError(http.StatusForbidden, "metadata, end_user_id and webhook can only be set with an API key")
	}
	out := map[string]any{}
	if req.AppMetadata != nil {
		out[appMetadataKey] = req.AppMetadata
	}
	if req.EndUserID != nil {
		out[endUserIDKey] = *req.EndUserID
	}
	if req.Webhook != nil {
		if s.d.WebhookURL == nil {
			return nil, errors.New("webhook URL validation is not wired")
		}
		if err := s.d.WebhookURL(ctx, req.Webhook.URL); err != nil {
			return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "webhook.url: "+err.Error())
		}
		out[webhookKey] = map[string]any{"url": req.Webhook.URL, "signed": req.Webhook.Secret != nil}
	}
	return out, nil
}

// provenanceOf is TaskProvenance.started_by_caller.
func provenanceOf(c authn.Caller) api.TaskProvenance {
	if c.Subject != nil && c.Subject.Kind == authn.SubjectAgent {
		return api.TaskProvenance{OriginType: "agent", OriginID: c.Subject.ID}
	}
	origin := "user"
	if c.Credential != nil && c.Credential.Kind == authn.KindAPIKey {
		origin = "api"
	}
	return api.TaskProvenance{OriginType: origin, OriginID: c.UserID, SourceIdentity: "user:" + c.UserID}
}

func sourceUserID(p api.TaskProvenance) string {
	return strings.TrimPrefix(p.SourceIdentity, "user:")
}

// Created is a started task and the agent it runs.
type Created struct {
	Task      Task
	AgentName string
}

// Create stores a task a caller starts and launches its workflow
// (create_task_for_agent_*). A refusal of the run itself is a *Refusal; an
// unknown agent, a bad request or an attachment that cannot be staged is an
// *httpx.Error. AgentName is set whenever the agent exists.
func (s *Surface) Create(ctx context.Context, req CreateRequest) (Created, error) {
	var out Created
	c, err := caller(ctx)
	if err != nil {
		return out, err
	}
	def, err := s.definition(ctx, c.Workspace, req.AgentID)
	var r *Refusal
	if errors.As(err, &r) {
		return out, r.HTTP()
	}
	if err != nil {
		return out, s.internal(ctx, "Task creation failed", err)
	}
	out.AgentName = def.Name
	trusted, err := s.trustedMetadata(ctx, c, req)
	if err != nil {
		return out, err
	}
	taskID := uuid.NewString()
	params := map[string]any{}
	for k, v := range req.Parameters {
		params[k] = v
	}
	meta := map[string]any{"created_via": "api"}
	for k, v := range trusted {
		meta[k] = v
	}
	if req.ProjectID != nil {
		meta["project_id"] = *req.ProjectID
	}
	if len(req.Attachments) > 0 {
		descriptors, err := s.stageAttachments(ctx, c, taskID, req.Attachments)
		if err != nil {
			return out, err
		}
		params["attachments"] = descriptors
		meta["workspace_attachments"] = descriptors
	}
	spec := runSpec{
		TaskID: taskID, AgentID: req.AgentID, Description: req.Description, Parameters: params,
		UserID: c.UserID, RequiresHumanApproval: req.RequiresHumanApproval, TaskPolicy: req.TaskPolicy,
		ExecutionTurns: req.ExecutionTurns, Metadata: meta, Provenance: provenanceOf(c), ScheduledAt: req.ScheduledAt,
	}
	if err := s.start(ctx, c.Workspace, spec); err != nil {
		if errors.As(err, &r) {
			return out, err
		}
		return out, s.internal(ctx, "Task creation failed", err)
	}
	if len(req.Attachments) > 0 {
		s.deleteStaging(ctx, c, req.Attachments)
	}
	if req.Webhook != nil && req.Webhook.Secret != nil {
		if err := s.storeWebhookSecret(ctx, c, taskID, *req.Webhook.Secret); err != nil {
			return out, s.internal(ctx, "Failed to store the task webhook secret", err)
		}
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil {
		return out, s.internal(ctx, "Failed to read the created task", err)
	}
	if !ok {
		return out, s.internal(ctx, "Failed to read the created task", fmt.Errorf("task %s vanished after creation", taskID))
	}
	out.Task = t
	return out, nil
}

// TaskResponse is TaskResponse.from_agent_task for the caller.
func (s *Surface) TaskResponse(ctx context.Context, t Task) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	return TaskResponseJSON(t, c), nil
}

func (s *Surface) storeWebhookSecret(ctx context.Context, c authn.Caller, taskID, secret string) error {
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		return s.d.Secrets(tx, c.UserID).Set(ctx, "task_webhook:"+taskID, secret)
	})
}

func (s *Surface) definition(ctx context.Context, ws scope.Workspace, agentID string) (agentsapi.Definition, error) {
	def, err := s.d.Definitions.Definition(ctx, ws, agentID)
	if errors.Is(err, agentsapi.ErrNotFound) {
		return def, refused(http.StatusNotFound, httpx.CodeNotFound, "Agent not found", "agent_not_found", api.ErrAgentNotFound)
	}
	return def, err
}

// dedupeName is _dedupe_attachment_name.
func dedupeName(name string, used map[string]bool) string {
	if !used[name] {
		return name
	}
	ext := path.Ext(name)
	base := strings.TrimSuffix(name, ext)
	for i := 1; ; i++ {
		candidate := base + "-" + strconv.Itoa(i) + ext
		if !used[candidate] {
			return candidate
		}
	}
}

// stageAttachments is _stage_attachments_into_task: each staging upload is
// copied into the reserved task's workspace under inputs/attachments/.
func (s *Surface) stageAttachments(ctx context.Context, c authn.Caller, taskID string, refs []string) ([]any, error) {
	if s.d.Files == nil || s.d.Workspaces == nil {
		return nil, errors.New("attachments need the sandbox file ports")
	}
	used := map[string]bool{}
	out := make([]any, 0, len(refs))
	for _, ref := range refs {
		if !strings.HasPrefix(ref, "staging/") {
			return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "Invalid attachment ref: "+ref)
		}
		head, found, err := s.d.Files.Head(ctx, c.Workspace, ref)
		if errors.Is(err, sandboxapi.ErrInvalidPath) {
			return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "Invalid attachment ref: "+ref)
		}
		if err != nil {
			return nil, s.internal(ctx, "Failed to read a staged attachment", err)
		}
		if !found {
			return nil, httpx.NotFound("attachment ref not found")
		}
		if head.SHA256 == "" {
			return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "attachment integrity digest is unavailable")
		}
		contentType := head.ContentType
		if contentType == "" {
			contentType = "application/octet-stream"
		}
		base := ref[strings.LastIndex(ref, "/")+1:]
		if base == "" {
			base = "attachment"
		}
		name := dedupeName(base, used)
		used[name] = true
		rel := "inputs/attachments/" + name
		_, err = s.d.Workspaces.AttachObject(ctx, c.Workspace.ID(), taskID, rel,
			sandboxapi.AttachSource{Key: ref, SHA256: head.SHA256, Size: head.Size, ContentType: contentType},
			sandboxapi.WriteOptions{Owner: "task-attachment-upload-" + taskID})
		switch {
		case errors.Is(err, sandboxapi.ErrWorkspaceQuota):
			return nil, httpx.HTTPError(http.StatusRequestEntityTooLarge, err.Error())
		case errors.Is(err, sandboxapi.ErrWorkspaceConflict):
			return nil, httpx.HTTPError(http.StatusConflict, err.Error())
		case errors.Is(err, sandboxapi.ErrWorkspaceInvalid):
			return nil, httpx.HTTPError(http.StatusUnprocessableEntity, err.Error())
		case err != nil:
			s.d.Log.ErrorContext(ctx, "Failed to attach staged object", "task_id", taskID, "error", err.Error())
			return nil, httpx.HTTPError(http.StatusInternalServerError, "Attachment storage failed").Wrap(err)
		}
		out = append(out, map[string]any{
			"relative_path": rel, "filename": name, "size": head.Size, "content_type": contentType, "sha256": head.SHA256,
		})
	}
	return out, nil
}

// deleteStaging is _delete_staging_refs: a failure is logged, never raised.
func (s *Surface) deleteStaging(ctx context.Context, c authn.Caller, refs []string) {
	for _, ref := range refs {
		if err := s.d.Files.Delete(ctx, c.Workspace, c.UserID, ref); err != nil {
			s.d.Log.WarnContext(ctx, "Failed to delete consumed staging ref", "ref", ref, "error", err.Error())
		}
	}
}

// runSpec is create_task_with_policy's input.
type runSpec struct {
	TaskID, AgentID, Description string
	Parameters                   map[string]any
	UserID                       string
	RequiresHumanApproval        bool
	TaskPolicy                   *governanceapi.Policy
	ExecutionTurns               *int64
	Metadata                     map[string]any
	Provenance                   api.TaskProvenance
	ScheduledAt                  *time.Time
}

// start is create_and_execute_task_with_workflow: the policy resolved and
// enforced, the agent checked, the task stored, then its workflow launched.
// A launch that fails leaves the task failed.
func (s *Surface) start(ctx context.Context, ws scope.Workspace, sp runSpec) error {
	if sp.UserID == "" {
		return errors.New("user_id is required to create a task; refusing to persist an unowned task")
	}
	maxIterations := sp.Parameters["max_iterations"]
	effective, snap, err := s.d.Policies.Task(ctx, governanceapi.RunPrincipal{Workspace: ws, UserID: sourceUserID(sp.Provenance), AgentID: sp.AgentID},
		governanceapi.TaskRequest{TaskPolicy: sp.TaskPolicy, ExecutionTurns: sp.ExecutionTurns, MaxIterations: maxIterations, RequiresHumanApproval: sp.RequiresHumanApproval})
	if errors.Is(err, governanceapi.ErrPolicyRefused) {
		s.d.Log.InfoContext(ctx, "Task policy rejected", "agent_id", sp.AgentID, "reason", err.Error())
		return refused(http.StatusUnprocessableEntity, "http_error", "Task policy rejected", "policy_validation_error", fmt.Errorf("%w: %w", api.ErrTaskPolicyRejected, err))
	}
	if err != nil {
		return err
	}
	delete(sp.Parameters, "max_iterations")
	if err := s.enforceBudget(ctx, ws, effective.Budget, sp.AgentID); err != nil {
		return err
	}
	def, err := s.definition(ctx, ws, sp.AgentID)
	if err != nil {
		return err
	}
	if def.Archived {
		return refused(http.StatusConflict, httpx.CodeConflict, fmt.Sprintf("Agent %s is archived; restore it first", sp.AgentID), "agent_archived", api.ErrAgentArchived)
	}
	if def.ClientID == "" && !truthy(sp.Parameters["model_override"]) && def.ModelID == "" {
		return refused(http.StatusUnprocessableEntity, "http_error", "Agent model is not configured", "model_not_configured", api.ErrModelNotConfigured)
	}
	meta := map[string]any{}
	for k, v := range sp.Metadata {
		meta[k] = v
	}
	if def.ClientID != "" {
		meta[runnerKey] = def.ClientID
	}
	if _, ok := meta["created_via"]; !ok {
		meta["created_via"] = "api"
	}
	meta["agent_name"] = def.Name
	meta["requires_human_approval"] = sp.RequiresHumanApproval
	meta["governance_snapshot"] = snap.Stored()
	row := store.NewSurfaceTask{
		ID: sp.TaskID, AgentID: sp.AgentID, Description: sp.Description, Status: "pending", CreatedBy: sp.UserID,
		Parameters: sp.Parameters, Metadata: meta, ScheduledAt: sp.ScheduledAt,
		OriginType: sp.Provenance.OriginType, OriginID: sp.Provenance.OriginID, CorrelationID: sp.Provenance.CorrelationID,
		CausationID: sp.Provenance.CausationID, ParentTaskID: sp.Provenance.ParentTaskID, SourceIdentity: sp.Provenance.SourceIdentity,
		TaskDefinitionID: sp.Provenance.TaskDefinitionID, Depth: int32(sp.Provenance.Depth), //nolint:gosec // a causation depth
	}
	var stored store.StoredTask
	if err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		if err := store.InsertSurfaceTask(ctx, tx, row, s.d.Now()); err != nil {
			return err
		}
		stored, err = store.Runs{}.TaskToLaunch(ctx, tx, sp.TaskID)
		return err
	}); err != nil {
		return err
	}
	return s.launch(ctx, ws, stored)
}

// launch is TemporalTaskManager.submit_task on a stored task.
func (s *Surface) launch(ctx context.Context, ws scope.Workspace, t store.StoredTask) error {
	launched, err := s.d.Launcher.Launch(ctx, ws.ID(), t)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to start the task's workflow", "task_id", t.ID, "error", err.Error())
		if werr := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
			_, err := store.SetSurfaceTaskStatus(ctx, tx, t.ID, "failed", "Task dispatch failed", s.d.Now())
			return err
		}); werr != nil {
			s.d.Log.ErrorContext(ctx, "Failed to mark an undispatched task failed", "task_id", t.ID, "error", werr.Error())
		}
		return refused(http.StatusServiceUnavailable, "http_error", "Task dispatch failed", "creation_failed", fmt.Errorf("%w: %w", api.ErrTaskDispatchFailed, err))
	}
	status := "running"
	if launched.Scheduled {
		status = "scheduled"
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		ok, err := store.Runs{}.MarkLaunched(ctx, tx, t.ID, status, launched.ExecutionID, s.d.Now())
		if err == nil && !ok {
			err = fmt.Errorf("failed to update task %s status", t.ID)
		}
		return err
	})
}

func monthStartUTC(t time.Time) time.Time {
	t = t.UTC()
	return time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, time.UTC)
}

// enforceBudget is _enforce_budget_cap with the run's effective budget.
func (s *Surface) enforceBudget(ctx context.Context, ws scope.Workspace, b *governanceapi.Budget, agentID string) (err error) {
	defer func() {
		if r := (*Refusal)(nil); errors.As(err, &r) {
			analytics.Count(s.d.Counter, "run_refused", map[string]string{"reason": "budget_cap"})
		}
	}()
	if b == nil || (b.MonthlySpendCapUSD == nil && b.AgentMonthlySpendCapUSD == nil && len(b.SpendCaps) == 0) {
		return nil
	}
	currency := s.d.Currency()
	since := monthStartUTC(s.d.Now())
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	sum := func(cur string, scope store.SpendScope) (money.Decimal, error) {
		raw, err := store.Runs{}.SumSpendSince(ctx, sess, since, cur, scope)
		if err != nil {
			return money.Decimal{}, err
		}
		return money.Parse(raw)
	}
	if c := b.MonthlySpendCapUSD; c != nil {
		spent, err := sum(currency, store.SpendScope{})
		if err != nil {
			return err
		}
		if spent.Cmp(*c) >= 0 {
			return capRefusal(ws, spent, *c, currency, "", false)
		}
	}
	if c := b.AgentMonthlySpendCapUSD; c != nil && agentID != "" {
		spent, err := sum(currency, store.SpendScope{AgentID: agentID})
		if err != nil {
			return err
		}
		if spent.Cmp(*c) >= 0 {
			return capRefusal(ws, spent, *c, currency, agentID, false)
		}
	}
	for _, c := range b.SpendCaps {
		if c.Category == nil || *c.Category != "llm" || (c.Period != nil && *c.Period == "run") {
			continue
		}
		if c.OwnAgent && agentID == "" {
			continue
		}
		cur := currency
		if c.Currency != nil && *c.Currency != "" {
			cur = *c.Currency
		}
		sc := store.SpendScope{Category: domain.CostModel}
		owner := ""
		if c.OwnAgent {
			sc.AgentID, owner = agentID, agentID
		}
		spent, err := sum(cur, sc)
		if err != nil {
			return err
		}
		if spent.Cmp(c.AmountUSD) >= 0 {
			return capRefusal(ws, spent, c.AmountUSD, cur, owner, true)
		}
	}
	return nil
}

func decimalFloat(d money.Decimal) float64 {
	f, _ := strconv.ParseFloat(d.String(), 64)
	return f
}

// capRefusal is BudgetCapExceededError as the routes answer it.
func capRefusal(ws scope.Workspace, spent, limit money.Decimal, currency, agentID string, llm bool) *Refusal {
	who, kind := "Workspace", "spend"
	if agentID != "" {
		who = "Agent"
	}
	if llm {
		kind = "LLM spend"
	}
	r := refused(http.StatusPaymentRequired, "budget_cap_exceeded",
		fmt.Sprintf("%s monthly %s cap reached (%s %s/%s %s)", who, kind, spent, currency, limit, currency),
		"monthly_spend_cap_exceeded", api.ErrSpendCapReached)
	r.Extra = wirejson.Object{
		{Key: "current_mtd_usd", Value: decimalFloat(spent)}, {Key: "cap_usd", Value: decimalFloat(limit)},
		{Key: "currency", Value: currency}, {Key: "workspace_id", Value: ws.ID()},
	}
	if agentID != "" {
		r.Extra = append(r.Extra, wirejson.Member{Key: "agent_id", Value: agentID})
	}
	return r
}
