package handlers

import (
	"context"
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/streams"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

// mountTriggerReads registers a trigger's history, metrics, status and the trigger health route.
func mountTriggerReads(base chi.Router, w *gen.ServerInterfaceWrapper) {
	p := httpx.WorkspacePrefix + "/triggers"
	base.Get(p+"/health", w.TriggersHealthCheckV1TriggersHealthGet)
	base.Get(p+"/{trigger_id}/executions", w.GetExecutionHistoryV1TriggersTriggerIdExecutionsGet)
	base.Get(p+"/{trigger_id}/status", w.GetTriggerStatusV1TriggersTriggerIdStatusGet)
	base.Get(p+"/{trigger_id}/metrics", w.GetExecutionMetricsV1TriggersTriggerIdMetricsGet)
	base.Get(p+"/{trigger_id}/timeline", w.GetExecutionTimelineV1TriggersTriggerIdTimelineGet)
	base.Get(p+"/{trigger_id}/correlations", w.GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGet)
}

// queryInt is an int query parameter with FastAPI's ge/le bounds; def when absent.
func queryInt(v *int, def int, lo, hi int64, name string, errs *[]httpx.FieldError) int {
	if v == nil {
		return def
	}
	n, fe := httpx.ValidateInt(strconv.Itoa(*v), httpx.IntBounds{Ge: lo, HasGe: true, Le: hi, HasLe: true}, "query", name)
	if fe != nil {
		*errs = append(*errs, *fe)
		return def
	}
	return int(n)
}

func naiveUTC(t *time.Time) *time.Time {
	if t == nil {
		return nil
	}
	u := t.UTC()
	return &u
}

type executionJSON struct {
	ID              string         `json:"id"`
	TriggerID       string         `json:"trigger_id"`
	ExecutedAt      time.Time      `json:"executed_at"`
	Status          string         `json:"status"`
	TaskID          *string        `json:"task_id"`
	ExecutionTimeMs int            `json:"execution_time_ms"`
	ErrorMessage    *string        `json:"error_message"`
	TriggerData     map[string]any `json:"trigger_data"`
	WorkflowID      *string        `json:"workflow_id"`
	RunID           *string        `json:"run_id"`
	FiredBy         *string        `json:"fired_by"`
	CostUSD         *float64       `json:"cost_usd"`
}

type pageJSON[T any] struct {
	Executions []T  `json:"executions"`
	Total      int  `json:"total"`
	Page       int  `json:"page"`
	PageSize   int  `json:"page_size"`
	HasNext    bool `json:"has_next"`
}

func (s *Server) GetExecutionHistoryV1TriggersTriggerIdExecutionsGet(ctx context.Context, req gen.GetExecutionHistoryV1TriggersTriggerIdExecutionsGetRequestObject) (gen.GetExecutionHistoryV1TriggersTriggerIdExecutionsGetResponseObject, error) {
	var errs []httpx.FieldError
	q := service.ExecutionQuery{
		Page:     queryInt(req.Params.Page, 1, 1, httpx.MaxPage, "page", &errs),
		PageSize: queryInt(req.Params.PageSize, 50, 1, 100, "page_size", &errs),
		Status:   req.Params.Status, Start: naiveUTC(req.Params.StartTime), End: naiveUTC(req.Params.EndTime),
	}
	if err := httpx.Validation(errs...); err != nil {
		return nil, err
	}
	id := req.TriggerId.String()
	pg, err := s.svc.Executions(ctx, id, q)
	if err != nil {
		return nil, notFound(id, err)
	}
	out := pageJSON[executionJSON]{Executions: make([]executionJSON, 0, len(pg.Executions)), Total: pg.Total,
		Page: pg.Page, PageSize: pg.PageSize, HasNext: pg.HasNext}
	for _, e := range pg.Executions {
		out.Executions = append(out.Executions, executionJSON{
			ID: e.ID, TriggerID: e.TriggerID, ExecutedAt: e.ExecutedAt, Status: e.Status, TaskID: e.TaskID,
			ExecutionTimeMs: e.ExecutionTimeMs, ErrorMessage: e.ErrorMessage, TriggerData: e.TriggerData,
			WorkflowID: e.WorkflowID, RunID: e.RunID, FiredBy: e.FiredBy, CostUSD: e.CostUSD,
		})
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) GetTriggerStatusV1TriggersTriggerIdStatusGet(ctx context.Context, req gen.GetTriggerStatusV1TriggersTriggerIdStatusGetRequestObject) (gen.GetTriggerStatusV1TriggersTriggerIdStatusGetResponseObject, error) {
	id := req.TriggerId.String()
	st, err := s.svc.Status(ctx, id)
	if err != nil {
		return nil, notFound(id, err)
	}
	t := st.Trigger
	return response{status: http.StatusOK, body: map[string]any{
		"trigger_id": id, "is_active": t.IsActive, "last_execution_at": t.LastExecutionAt,
		"consecutive_failures": t.Consecutive, "should_disable_due_to_failures": t.ShouldDisable(),
		"schedule_info": st.ScheduleInfo,
	}}, nil
}

func (s *Server) GetExecutionMetricsV1TriggersTriggerIdMetricsGet(ctx context.Context, req gen.GetExecutionMetricsV1TriggersTriggerIdMetricsGetRequestObject) (gen.GetExecutionMetricsV1TriggersTriggerIdMetricsGetResponseObject, error) {
	var errs []httpx.FieldError
	var hours *int
	if req.Params.Hours != nil {
		h := queryInt(req.Params.Hours, 0, 1, 8760, "hours", &errs)
		hours = &h
	}
	if err := httpx.Validation(errs...); err != nil {
		return nil, err
	}
	id := req.TriggerId.String()
	m, err := s.svc.Metrics(ctx, id, hours)
	if err != nil {
		return nil, notFound(id, err)
	}
	return response{status: http.StatusOK, body: map[string]any{
		"trigger_id": id, "period_hours": m.PeriodHours,
		"total_executions": m.Total, "successful_executions": m.Successful, "failed_executions": m.Failed,
		"timeout_executions": m.TimedOut, "skipped_executions": m.Skipped,
		"success_rate": m.SuccessRate, "failure_rate": m.FailureRate,
		"avg_execution_time_ms": m.AvgMs, "min_execution_time_ms": m.MinMs, "max_execution_time_ms": m.MaxMs,
		"total_cost_usd": m.TotalCostUSD, "avg_cost_usd": m.AvgCostUSD, "costed_executions": m.CostedExecutions,
	}}, nil
}

func (s *Server) GetExecutionTimelineV1TriggersTriggerIdTimelineGet(ctx context.Context, req gen.GetExecutionTimelineV1TriggersTriggerIdTimelineGetRequestObject) (gen.GetExecutionTimelineV1TriggersTriggerIdTimelineGetResponseObject, error) {
	var errs []httpx.FieldError
	hours := queryInt(req.Params.Hours, 24, 1, 168, "hours", &errs)
	bucket := queryInt(req.Params.BucketSizeMinutes, 60, 5, 1440, "bucket_size_minutes", &errs)
	if err := httpx.Validation(errs...); err != nil {
		return nil, err
	}
	id := req.TriggerId.String()
	buckets, err := s.svc.Timeline(ctx, id, hours, bucket)
	if err != nil {
		return nil, notFound(id, err)
	}
	timeline := make([]map[string]any, 0, len(buckets))
	for _, b := range buckets {
		rate := 0.0
		if b.Total > 0 {
			rate = float64(b.Successful) / float64(b.Total) * 100
		}
		timeline = append(timeline, map[string]any{
			"time_bucket": b.Start, "total_count": b.Total, "success_count": b.Successful,
			"failed_count": b.Failed, "timeout_count": b.TimedOut, "success_rate": rate,
		})
	}
	return response{status: http.StatusOK, body: map[string]any{"trigger_id": id, "period_hours": hours, "timeline": timeline}}, nil
}

func (s *Server) GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGet(ctx context.Context, req gen.GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetRequestObject) (gen.GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetResponseObject, error) {
	var errs []httpx.FieldError
	page := queryInt(req.Params.Page, 1, 1, httpx.MaxPage, "page", &errs)
	size := queryInt(req.Params.PageSize, 50, 1, 100, "page_size", &errs)
	if err := httpx.Validation(errs...); err != nil {
		return nil, err
	}
	id := req.TriggerId.String()
	rows, total, err := s.svc.Correlations(ctx, id, page, size)
	if err != nil {
		return nil, notFound(id, err)
	}
	out := pageJSON[map[string]any]{Executions: make([]map[string]any, 0, len(rows)), Total: total, Page: page,
		PageSize: size, HasNext: (page-1)*size+size < total}
	for _, e := range rows {
		out.Executions = append(out.Executions, correlation(e))
	}
	return response{status: http.StatusOK, body: out}, nil
}

func correlation(e domain.Execution) map[string]any {
	return map[string]any{
		"id": e.ID, "trigger_id": e.TriggerID, "executed_at": e.ExecutedAt, "status": e.Status, "task_id": e.TaskID,
		"execution_time_ms": e.ExecutionTimeMs, "error_message": e.ErrorMessage, "trigger_data": e.TriggerData,
		"workflow_id": e.WorkflowID, "run_id": e.RunID,
		"has_task_correlation": e.TaskID != nil, "has_workflow_correlation": e.WorkflowID != nil,
	}
}

func (s *Server) TriggersHealthCheckV1TriggersHealthGet(ctx context.Context, _ gen.TriggersHealthCheckV1TriggersHealthGetRequestObject) (gen.TriggersHealthCheckV1TriggersHealthGetResponseObject, error) {
	return response{status: http.StatusOK, body: s.svc.Health(ctx)}, nil
}

func (x response) VisitGetExecutionHistoryV1TriggersTriggerIdExecutionsGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitGetTriggerStatusV1TriggersTriggerIdStatusGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitGetExecutionMetricsV1TriggersTriggerIdMetricsGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitGetExecutionTimelineV1TriggersTriggerIdTimelineGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitGetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitTriggersHealthCheckV1TriggersHealthGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
