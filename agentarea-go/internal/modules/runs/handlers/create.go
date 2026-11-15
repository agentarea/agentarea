package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

// taskMetadataMaxBytes is TASK_METADATA_MAX_BYTES.
const taskMetadataMaxBytes = 4096

// reservedParameters are RESERVED_TASK_PARAMETERS, in sorted order.
func reservedParameters() []string {
	return []string{"delivery_address", "follow_up_message", "session", "trigger_event", "trigger_event_file"}
}

// integer is a pydantic int field: an integral JSON number.
func integer(o wirejson.Object, key string, loc []any, errs *[]httpx.FieldError) (int64, bool) {
	v, ok := o.Get(key)
	if !ok {
		return 0, false
	}
	l := at(loc, key)
	switch x := v.(type) {
	case json.Number:
		n, err := x.Int64()
		if err != nil {
			*errs = append(*errs, httpx.IntFromFloat(l...))
			return 0, false
		}
		return n, true
	case wirejson.Float:
		f := float64(x)
		if f != float64(int64(f)) {
			*errs = append(*errs, httpx.IntFromFloat(l...))
			return 0, false
		}
		return int64(f), true
	case string:
		n, fe := httpx.ValidateInt(strings.TrimSpace(x), httpx.IntBounds{}, l...)
		if fe != nil {
			*errs = append(*errs, *fe)
			return 0, false
		}
		return n, true
	}
	*errs = append(*errs, httpx.IntType(l...))
	return 0, false
}

func boundedInt(o wirejson.Object, key string, lo, hi int64, loc []any, errs *[]httpx.FieldError) int64 {
	n, ok := integer(o, key, loc, errs)
	if !ok {
		return 0
	}
	if n < lo {
		*errs = append(*errs, httpx.GreaterThanEqual(lo, at(loc, key)...))
		return 0
	}
	if n > hi {
		*errs = append(*errs, httpx.LessThanEqual(hi, at(loc, key)...))
		return 0
	}
	return n
}

// parametersOf is TaskCreate.parameters: an object no caller may write the
// trigger's keys into, whose model_override names a model instance.
func parametersOf(o wirejson.Object, loc []any, errs *[]httpx.FieldError) map[string]any {
	v, ok := o.Get("parameters")
	if !ok {
		return map[string]any{}
	}
	l := at(loc, "parameters")
	obj, isObj := v.(wirejson.Object)
	if !isObj {
		*errs = append(*errs, httpx.DictType(l...))
		return nil
	}
	var hit []string
	for _, k := range reservedParameters() {
		if _, present := obj.Get(k); present {
			hit = append(hit, k)
		}
	}
	if len(hit) > 0 {
		*errs = append(*errs, httpx.ValueError(strings.Join(hit, ", ")+" is set by the trigger that received the event and cannot be supplied", l...))
		return nil
	}
	if mo, present := obj.Get("model_override"); present && mo != nil && mo != "" {
		s, isStr := mo.(string)
		if _, fe := httpx.ValidateUUID(s, "body"); !isStr || fe != nil {
			*errs = append(*errs, httpx.ValueError("model_override must be a model instance id", l...))
			return nil
		}
	}
	m, _ := plain(obj).(map[string]any)
	return m
}

// createBody is TaskCreate.
func createBody(v any, in *input, errs *[]httpx.FieldError) {
	loc := []any{"body"}
	o, ok := model(v, loc, errs)
	if !ok {
		return
	}
	in.create = taskCreate(o, loc, errs)
}

// scheduleBody is ScheduleTaskCreate: TaskCreate with a future, offset-aware scheduled_at.
func scheduleBody(v any, in *input, errs *[]httpx.FieldError) {
	loc := []any{"body"}
	o, ok := model(v, loc, errs)
	if !ok {
		return
	}
	in.create = taskCreate(o, loc, errs)
	raw, present := o.Get("scheduled_at")
	l := at(loc, "scheduled_at")
	if !present {
		*errs = append(*errs, httpx.Missing(l...))
		return
	}
	s, isStr := raw.(string)
	if !isStr {
		*errs = append(*errs, httpx.FieldError{Type: "datetime_type", Loc: l, Msg: "Input should be a valid datetime"})
		return
	}
	t, aware, err := parseInstant(s)
	switch {
	case err != nil:
		*errs = append(*errs, httpx.FieldError{Type: "datetime_from_date_parsing", Loc: l, Msg: "Input should be a valid datetime or date, " + err.Error()})
	case !aware:
		*errs = append(*errs, httpx.ValueError("scheduled_at must include a UTC offset", l...))
	case !t.After(time.Now()):
		*errs = append(*errs, httpx.ValueError("scheduled_at must be in the future", l...))
	default:
		in.create.ScheduledAt = &t
	}
}

// parseInstant reads an ISO 8601 datetime; aware is whether it has an offset.
func parseInstant(s string) (time.Time, bool, error) {
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02 15:04:05.999999999Z07:00"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t, true, nil
		}
	}
	for _, layout := range []string{"2006-01-02T15:04:05.999999999", "2006-01-02 15:04:05.999999999", "2006-01-02T15:04", "2006-01-02"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t, false, nil
		}
	}
	return time.Time{}, false, errors.New("invalid character in datetime")
}

func taskCreate(o wirejson.Object, loc []any, errs *[]httpx.FieldError) service.CreateRequest {
	var req service.CreateRequest
	req.Description = required(o, "description", 0, 0, loc, errs)
	req.Parameters = parametersOf(o, loc, errs)
	if x, present := o.Get("execution"); present && x != nil {
		l := at(loc, "execution")
		if xo, ok := model(x, l, errs); ok {
			extraForbidden(xo, []string{"max_model_turns"}, l, errs)
			if n, ok := integer(xo, "max_model_turns", l, errs); ok {
				if n <= 0 {
					*errs = append(*errs, httpx.GreaterThan(0, at(l, "max_model_turns")...))
				} else {
					req.ExecutionTurns = &n
				}
			} else if _, has := xo.Get("max_model_turns"); !has {
				*errs = append(*errs, httpx.Missing(at(l, "max_model_turns")...))
			}
		}
	}
	if v, present := o.Get("requires_human_approval"); present && v != nil {
		req.RequiresHumanApproval, _ = boolean(o, "requires_human_approval", loc, errs)
	}
	req.ProjectID, _ = str(o, "project_id", 0, 0, true, loc, errs)
	if v, present := o.Get("task_policy"); present && v != nil {
		p, fes := governanceapi.ParsePolicy(v, at(loc, "task_policy"), false)
		*errs = append(*errs, fes...)
		if len(fes) == 0 {
			req.TaskPolicy = &p
		}
	}
	if v, present := o.Get("attachments"); present && v != nil {
		l := at(loc, "attachments")
		list, isList := v.([]any)
		if !isList {
			*errs = append(*errs, httpx.ListType(l...))
		}
		for i, item := range list {
			s, isStr := item.(string)
			if !isStr {
				*errs = append(*errs, httpx.StringType(at(l, i)...))
				continue
			}
			req.Attachments = append(req.Attachments, s)
		}
	}
	if v, present := o.Get("metadata"); present && v != nil {
		l := at(loc, "metadata")
		if mo, isObj := v.(wirejson.Object); !isObj {
			*errs = append(*errs, httpx.DictType(l...))
		} else if raw, err := wirejson.Marshal(mo, wirejson.Compact); err != nil {
			*errs = append(*errs, httpx.ValueError("metadata must be JSON-serializable", l...))
		} else if len(raw) > taskMetadataMaxBytes {
			*errs = append(*errs, httpx.ValueError("metadata must be at most 4096 bytes of JSON", l...))
		} else {
			req.AppMetadata = plain(mo)
		}
	}
	req.EndUserID, _ = str(o, "end_user_id", 1, 256, true, loc, errs)
	if v, present := o.Get("webhook"); present && v != nil {
		l := at(loc, "webhook")
		if wo, ok := model(v, l, errs); ok {
			extraForbidden(wo, []string{"url", "secret"}, l, errs)
			u := required(wo, "url", 1, 2048, l, errs)
			secret, _ := str(wo, "secret", 32, 512, true, l, errs)
			req.Webhook = &service.Webhook{URL: u, Secret: secret}
		}
	}
	return req
}

// continueBody is ContinueTaskPayload.
func continueBody(v any, in *input, errs *[]httpx.FieldError) {
	loc := []any{"body"}
	o, ok := model(v, loc, errs)
	if !ok {
		return
	}
	extraForbidden(o, []string{"additional_iterations", "additional_budget_usd", "additional_tokens", "additional_tool_calls"}, loc, errs)
	in.continuation.Iterations = boundedInt(o, "additional_iterations", 0, 1000, loc, errs)
	in.continuation.Tokens = boundedInt(o, "additional_tokens", 0, 10_000_000, loc, errs)
	in.continuation.ToolCalls = boundedInt(o, "additional_tool_calls", 0, 10_000, loc, errs)
	if b, present := o.Get("additional_budget_usd"); present && b != nil {
		l := at(loc, "additional_budget_usd")
		d, err := moneyOf(b)
		switch {
		case err != nil:
			*errs = append(*errs, httpx.ValueError(err.Error(), l...))
		case d.Cmp(money.Decimal{}) <= 0:
			*errs = append(*errs, httpx.GreaterThan(0, l...))
		default:
			in.continuation.Budget = &d
		}
	}
}

// followQuery is the streaming create's follow flag.
func followQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	in.follow = false
	if v, ok := last(q, "follow"); ok {
		b, valid := httpx.ParseBool(v)
		if !valid {
			*errs = append(*errs, httpx.BoolParsing("query", "follow"))
			return nil
		}
		in.follow = b
	}
	return nil
}

// sandboxPrefixQuery is list_task_sandbox_files' prefix.
func sandboxPrefixQuery(q url.Values, in *input, _ *[]httpx.FieldError) url.Values {
	in.prefix, _ = last(q, "prefix")
	return nil
}

// artifactsQuery is list_task_artifacts' expires_in, kept for old callers.
func artifactsQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	var expires int
	intParam(q, "expires_in", 3600, bounds(60, 86400), &expires, errs)
	return nil
}

func nowISO(now time.Time) string { return service.PyISO(now, false) }

// create is create_task_for_agent_with_stream: the run is started before the
// response, then its creation and its feed are streamed.
func (h *Server) create(errs *httpx.Errors) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		in := inputFrom(ctx)
		agentID := chiParam(r, "agent_id")
		req := in.create
		req.AgentID = agentID
		created, err := h.s.Create(ctx, req)
		var refusal *service.Refusal
		if err != nil && (!errors.As(err, &refusal) || len(req.Attachments) > 0) {
			if refusal != nil {
				err = refusal.HTTP()
			}
			errs.Write(w, r, err)
			return
		}
		var st *service.Stream
		if err == nil {
			t := created.Task
			if t.ExecutionID != nil && (t.Status == "running" || t.Status == "pending") {
				st, err = h.s.OpenStream(ctx, service.StreamRequest{AgentID: agentID, TaskID: t.ID, Follow: in.follow, Revealed: true, Quiet: true})
				if err != nil {
					errs.Write(w, r, err)
					return
				}
			}
		}
		sse, serr := httpx.StartSSE(w, r)
		if serr != nil {
			h.s.Log().ErrorContext(ctx, "Failed to start the task creation stream", "error", serr.Error())
			return
		}
		frames := make(chan []byte)
		runCtx, cancel := context.WithCancel(ctx)
		defer cancel()
		go func() {
			defer close(frames)
			emit := func(eventType string, data wirejson.Object, id string) error {
				frame, err := httpx.FormatSSE(eventType, data, id)
				if err != nil {
					return err
				}
				select {
				case frames <- frame:
					return nil
				case <-runCtx.Done():
					return runCtx.Err()
				}
			}
			if h.creationFrames(runCtx, emit, agentID, created, refusal, st) != nil && runCtx.Err() == nil && st != nil {
				_ = emit("error", st.ErrorFrame(h.s.Now()), "")
			}
		}()
		if err := sse.Pump(runCtx, frames, httpx.SSEHeartbeat); err != nil && ctx.Err() == nil {
			h.s.Log().InfoContext(ctx, "Task creation stream ended", "agent_id", agentID, "reason", err.Error())
		}
	}
}

func (h *Server) creationFrames(ctx context.Context, emit func(string, wirejson.Object, string) error, agentID string, created service.Created, refusal *service.Refusal, st *service.Stream) error {
	if err := emit("connected", wirejson.Object{
		{Key: "agent_id", Value: agentID}, {Key: "agent_name", Value: created.AgentName},
		{Key: "message", Value: "Starting task creation"}, {Key: "timestamp", Value: nowISO(h.s.Now())},
	}, ""); err != nil {
		return err
	}
	if refusal != nil {
		frame := wirejson.Object{}
		if refusal.Type == "creation_failed" {
			frame = append(frame, wirejson.Member{Key: "task_id", Value: nil})
		}
		frame = append(frame, wirejson.Member{Key: "agent_id", Value: agentID}, wirejson.Member{Key: "error", Value: refusal.Detail},
			wirejson.Member{Key: "error_type", Value: refusal.Type})
		for _, m := range refusal.Extra {
			if m.Key != "workspace_id" {
				frame = append(frame, m)
			}
		}
		frame = append(frame, wirejson.Member{Key: "timestamp", Value: nowISO(h.s.Now())})
		return emit("error", frame, "")
	}
	t := created.Task
	var execID any
	if t.ExecutionID != nil {
		execID = *t.ExecutionID
	}
	if err := emit("task_created", wirejson.Object{
		{Key: "task_id", Value: t.ID}, {Key: "agent_id", Value: agentID}, {Key: "description", Value: t.Description},
		{Key: "status", Value: t.Status}, {Key: "execution_id", Value: execID},
		{Key: "created_at", Value: service.PyISO(t.CreatedAt, true)}, {Key: "timestamp", Value: nowISO(h.s.Now())},
	}, ""); err != nil {
		return err
	}
	if st == nil {
		return emit("task_failed", wirejson.Object{
			{Key: "task_id", Value: t.ID}, {Key: "agent_id", Value: agentID}, {Key: "error", Value: "Task failed to start workflow"},
			{Key: "status", Value: t.Status}, {Key: "result", Value: t.Result}, {Key: "timestamp", Value: nowISO(h.s.Now())},
		}, "")
	}
	err := st.Run(ctx, emit)
	if err != nil && ctx.Err() == nil {
		h.s.Log().ErrorContext(ctx, "Error in task creation stream", "task_id", t.ID, "error", err.Error())
	}
	return err
}

func (h *Server) startSync(ctx context.Context, rq service.CreateRequest, agentID string) (service.Task, error) {
	rq.AgentID = agentID
	created, err := h.s.Create(ctx, rq)
	var refusal *service.Refusal
	if errors.As(err, &refusal) {
		return service.Task{}, refusal.HTTP()
	}
	return created.Task, err
}

// download streams a task file with the headers the sandbox port gave.
func download(w http.ResponseWriter, d sandboxapi.Download) (err error) {
	defer func() { err = errors.Join(err, d.Body.Close()) }()
	for k, vs := range d.Header {
		for _, v := range vs {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(http.StatusOK)
	_, err = io.Copy(w, d.Body)
	return err
}

// files serves the task file downloads, which stream bodies the strict
// handler cannot.
func (h *Server) files(errs *httpx.Errors, read func(ctx context.Context, r *http.Request) (sandboxapi.Download, error)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		d, err := read(r.Context(), r)
		if err != nil {
			errs.Write(w, r, err)
			return
		}
		if err := download(w, d); err != nil && r.Context().Err() == nil {
			h.s.Log().ErrorContext(r.Context(), "Failed to stream a task file", "path", r.URL.Path, "error", err.Error())
		}
	}
}
