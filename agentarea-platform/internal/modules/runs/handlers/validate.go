package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

// input is what a route's parameters and body validated to, kept in the
// request context for the handler: the generated binding cannot report
// pydantic's errors.
type input struct {
	statuses      []string
	status        *string
	createdBy     *string
	search        *string
	eventType     *string
	agentID       *string
	limit, offset int
	page, size    int
	includeChunks bool

	a2ui       service.A2UIAction
	submission service.InputSubmission
	command    service.Command
	resolution service.Resolution
	approved   bool
	comment    *string

	create       service.CreateRequest
	continuation service.Continuation
	follow       bool
	prefix       string
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

// request is one route's parameters: path UUIDs, then query, then body, in
// FastAPI's order; every error is reported in one 422. authority, when set,
// is requires_task_authority: it runs once task_id is valid, before the
// endpoint's own parameters are read.
type request struct {
	pathUUIDs []string
	query     func(q url.Values, in *input, errs *[]httpx.FieldError) url.Values
	body      func(v any, in *input, errs *[]httpx.FieldError)
	authority func(ctx context.Context, taskID string) error
	// execute, when set, is requires("execute", "agent") on agent_id.
	execute func(ctx context.Context, agentID string) error
}

func (rq request) middleware(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			var fes []httpx.FieldError
			var in input
			if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
				fes = append(fes, *fe)
			}
			if rq.authority != nil {
				if id, fe := httpx.ValidateUUID(chi.URLParam(r, "task_id"), "path", "task_id"); fe == nil && len(fes) == 0 {
					if err := rq.authority(r.Context(), id); err != nil {
						errs.Write(w, r, err)
						return
					}
				}
			}
			if rq.execute != nil {
				if id, fe := httpx.ValidateUUID(chi.URLParam(r, "agent_id"), "path", "agent_id"); fe == nil && len(fes) == 0 {
					if err := rq.execute(r.Context(), id); err != nil {
						errs.Write(w, r, err)
						return
					}
				}
			}
			for _, name := range rq.pathUUIDs {
				if _, fe := httpx.ValidateUUID(chi.URLParam(r, name), "path", name); fe != nil {
					fes = append(fes, *fe)
				}
			}
			if rq.query != nil {
				if q := rq.query(r.URL.Query(), &in, &fes); q != nil {
					r.URL.RawQuery = q.Encode()
				}
			}
			if rq.body != nil {
				v, err := readBody(r)
				if err != nil {
					errs.Write(w, r, err)
					return
				}
				rq.body(v, &in, &fes)
			}
			if err := httpx.Validation(fes...); err != nil {
				errs.Write(w, r, err)
				return
			}
			if rq.body != nil {
				r.Body = io.NopCloser(bytes.NewReader([]byte("{}")))
				r.ContentLength = 2
				r.Header.Set("Content-Type", "application/json")
			}
			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), inputKey{}, in)))
		})
	}
}

func last(q url.Values, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

func intParam(q url.Values, key string, def int, b httpx.IntBounds, out *int, errs *[]httpx.FieldError) {
	*out = def
	v, ok := last(q, key)
	if !ok {
		return
	}
	n, fe := httpx.ValidateInt(v, b, "query", key)
	if fe != nil {
		*errs = append(*errs, *fe)
		return
	}
	*out = int(n)
}

func bounds(lo, hi int64) httpx.IntBounds {
	return httpx.IntBounds{Ge: lo, HasGe: true, Le: hi, HasLe: true}
}

func strParam(q url.Values, key string) *string {
	if v, ok := last(q, key); ok {
		return &v
	}
	return nil
}

func set(out url.Values, key string, v *string) {
	if v != nil {
		out.Set(key, *v)
	}
}

// Query bounds of the routes.
const (
	MaxListLimit      = 1000
	DefaultListLimit  = 100
	MaxEventsPageSize = 100
	MaxInboxPageSize  = 200
	MaxApprovalsPage  = 10_000
)

// agentTasksQuery is list_agent_tasks' status, limit and offset.
func agentTasksQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	in.status = strParam(q, "status")
	intParam(q, "limit", DefaultListLimit, bounds(1, MaxListLimit), &in.limit, errs)
	intParam(q, "offset", 0, bounds(0, httpx.MaxOffset), &in.offset, errs)
	out := url.Values{"limit": {strconv.Itoa(in.limit)}, "offset": {strconv.Itoa(in.offset)}}
	set(out, "status", in.status)
	return out
}

// TaskStatuses() is TaskStatus in its declared order.
func TaskStatuses() []string {
	return []string{
		"submitted", "pending", "preparing", "scheduled", "running", "working", "waiting_for_input",
		"waiting_for_approval", "waiting_for_continuation", "waiting_for_infrastructure", "blocked",
		"completed", "failed", "cancelled",
	}
}

func oneOf(v string, choices []string) bool {
	for _, c := range choices {
		if v == c {
			return true
		}
	}
	return false
}

// allTasksQuery is get_all_tasks' filters.
func allTasksQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	out := url.Values{}
	if vs, ok := q["status"]; ok {
		in.statuses = []string{}
		for i, v := range vs {
			if !oneOf(v, TaskStatuses()) {
				*errs = append(*errs, httpx.LiteralError(TaskStatuses(), "query", "status", i))
				continue
			}
			in.statuses = append(in.statuses, v)
			out.Add("status", v)
		}
	}
	in.createdBy, in.search = strParam(q, "created_by"), strParam(q, "search")
	intParam(q, "limit", DefaultListLimit, bounds(1, MaxListLimit), &in.limit, errs)
	intParam(q, "offset", 0, bounds(0, httpx.MaxOffset), &in.offset, errs)
	out.Set("limit", strconv.Itoa(in.limit))
	out.Set("offset", strconv.Itoa(in.offset))
	set(out, "created_by", in.createdBy)
	set(out, "search", in.search)
	return out
}

// eventsQuery is get_task_events' page, page_size and event_type.
func eventsQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	intParam(q, "page", 1, bounds(1, httpx.MaxPage), &in.page, errs)
	intParam(q, "page_size", 50, bounds(1, MaxEventsPageSize), &in.size, errs)
	in.eventType = strParam(q, "event_type")
	out := url.Values{"page": {strconv.Itoa(in.page)}, "page_size": {strconv.Itoa(in.size)}}
	set(out, "event_type", in.eventType)
	return out
}

// streamQuery is stream_task_events' include_chunks.
func streamQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	in.includeChunks = true
	if v, ok := last(q, "include_chunks"); ok {
		b, valid := httpx.ParseBool(v)
		if !valid {
			*errs = append(*errs, httpx.BoolParsing("query", "include_chunks"))
		}
		in.includeChunks = b
	}
	return url.Values{"include_chunks": {strconv.FormatBool(in.includeChunks)}}
}

// inboxQuery is get_inbox_items' filters.
func inboxQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	out := url.Values{}
	if v, ok := last(q, "status"); ok {
		if oneOf(v, service.InboxStatuses()) {
			in.status = &v
			out.Set("status", v)
		} else {
			*errs = append(*errs, httpx.LiteralError(service.InboxStatuses(), "query", "status"))
		}
	}
	if v, ok := last(q, "agent_id"); ok {
		if id, fe := httpx.ValidateUUID(v, "query", "agent_id"); fe != nil {
			*errs = append(*errs, *fe)
		} else {
			in.agentID = &id
			out.Set("agent_id", id)
		}
	}
	intParam(q, "page", 1, bounds(1, httpx.MaxPage), &in.page, errs)
	intParam(q, "page_size", 100, bounds(1, MaxInboxPageSize), &in.size, errs)
	out.Set("page", strconv.Itoa(in.page))
	out.Set("page_size", strconv.Itoa(in.size))
	return out
}

// ApprovalStatuses() is ToolCallApprovalStatus in its declared order.
func ApprovalStatuses() []string {
	return []string{"pending", "approved", "rejected", "consumed", "expired"}
}

// approvalsQuery is list_tool_call_approvals' status, page and page_size.
func approvalsQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	out := url.Values{}
	if v, ok := last(q, "status"); ok {
		if oneOf(v, ApprovalStatuses()) {
			in.status = &v
			out.Set("status", v)
		} else {
			*errs = append(*errs, httpx.EnumError(ApprovalStatuses(), "query", "status"))
		}
	}
	intParam(q, "page", 1, bounds(1, MaxApprovalsPage), &in.page, errs)
	intParam(q, "page_size", 50, bounds(1, MaxInboxPageSize), &in.size, errs)
	out.Set("page", strconv.Itoa(in.page))
	out.Set("page_size", strconv.Itoa(in.size))
	return out
}

// decisionsQuery is list_approval_decisions' page and page_size.
func decisionsQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	out := url.Values{}
	intParam(q, "page", 1, bounds(1, httpx.MaxPage), &in.page, errs)
	intParam(q, "page_size", 50, bounds(1, MaxInboxPageSize), &in.size, errs)
	out.Set("page", strconv.Itoa(in.page))
	out.Set("page_size", strconv.Itoa(in.size))
	return out
}

// absent is a request body FastAPI saw none of.
type absent struct{}

// readBody is FastAPI's body read for a JSON body parameter.
func readBody(r *http.Request) (any, error) {
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	if len(raw) == 0 {
		return absent{}, nil
	}
	if ct := r.Header.Get("Content-Type"); ct != "" && !jsonContentType(ct) {
		return raw, nil
	}
	if err := httpx.CheckJSONBody(raw); err != nil {
		return nil, err
	}
	return wirejson.Unmarshal(raw)
}

func jsonContentType(ct string) bool {
	media, _, err := mime.ParseMediaType(ct)
	if err != nil {
		media = strings.ToLower(strings.TrimSpace(strings.SplitN(ct, ";", 2)[0]))
	}
	main, sub, _ := strings.Cut(media, "/")
	return main == "application" && (sub == "json" || strings.HasSuffix(sub, "+json"))
}

func model(v any, loc []any, errs *[]httpx.FieldError) (wirejson.Object, bool) {
	switch o := v.(type) {
	case wirejson.Object:
		return o, true
	case absent:
		*errs = append(*errs, httpx.Missing(loc...))
	default:
		*errs = append(*errs, httpx.ModelAttributesType(loc...))
	}
	return nil, false
}

func at(loc []any, key any) []any { return append(append([]any{}, loc...), key) }

func extraForbidden(o wirejson.Object, fields []string, loc []any, errs *[]httpx.FieldError) {
	for _, m := range o {
		if !oneOf(m.Key, fields) {
			*errs = append(*errs, httpx.ExtraForbidden(at(loc, m.Key)...))
		}
	}
}

// str is a str field with length bounds (0 = none); nullable admits null.
func str(o wirejson.Object, key string, minLen, maxLen int, nullable bool, loc []any, errs *[]httpx.FieldError) (value *string, present bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil && nullable {
		return nil, true
	}
	s, isStr := v.(string)
	l := at(loc, key)
	if !isStr {
		*errs = append(*errs, httpx.StringType(l...))
		return nil, true
	}
	n := utf8.RuneCountInString(s)
	if minLen > 0 && n < minLen {
		*errs = append(*errs, httpx.StringTooShort(minLen, l...))
		return nil, true
	}
	if maxLen > 0 && n > maxLen {
		*errs = append(*errs, httpx.StringTooLong(maxLen, l...))
		return nil, true
	}
	return &s, true
}

func required(o wirejson.Object, key string, minLen, maxLen int, loc []any, errs *[]httpx.FieldError) string {
	s, present := str(o, key, minLen, maxLen, false, loc, errs)
	if !present {
		*errs = append(*errs, httpx.Missing(at(loc, key)...))
	}
	if s == nil {
		return ""
	}
	return *s
}

// boolean is pydantic's lax bool: true/false, 0/1, or a bool-shaped string.
func boolean(o wirejson.Object, key string, loc []any, errs *[]httpx.FieldError) (bool, bool) {
	v, ok := o.Get(key)
	l := at(loc, key)
	if !ok {
		*errs = append(*errs, httpx.Missing(l...))
		return false, false
	}
	switch x := v.(type) {
	case bool:
		return x, true
	case string:
		if b, valid := httpx.ParseBool(x); valid {
			return b, true
		}
	case json.Number:
		switch x.String() {
		case "0":
			return false, true
		case "1":
			return true, true
		}
	case wirejson.Float:
		switch float64(x) {
		case 0:
			return false, true
		case 1:
			return true, true
		}
	default:
		*errs = append(*errs, httpx.BoolType(l...))
		return false, false
	}
	*errs = append(*errs, httpx.BoolParsing(l...))
	return false, false
}

func a2uiBody(v any, in *input, errs *[]httpx.FieldError) {
	loc := []any{"body"}
	o, ok := model(v, loc, errs)
	if !ok {
		return
	}
	in.a2ui.Name = required(o, "name", 0, 128, loc, errs)
	in.a2ui.SurfaceID = required(o, "surface_id", 0, 64, loc, errs)
	if s, _ := str(o, "source_component_id", 0, 128, false, loc, errs); s != nil {
		in.a2ui.SourceComponentID = *s
	}
	in.a2ui.Context = map[string]any{}
	if c, present := o.Get("context"); present {
		if obj, isObj := c.(wirejson.Object); isObj {
			in.a2ui.Context, _ = plain(obj).(map[string]any)
		} else {
			*errs = append(*errs, httpx.DictType(at(loc, "context")...))
		}
	}
	extraForbidden(o, []string{"name", "surface_id", "source_component_id", "context"}, loc, errs)
}

func plain(v any) any {
	switch x := v.(type) {
	case wirejson.Object:
		m := make(map[string]any, len(x))
		for _, mem := range x {
			m[mem.Key] = plain(mem.Value)
		}
		return m
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = plain(e)
		}
		return out
	case wirejson.Float:
		return float64(x)
	}
	return v
}

// inputBody is TaskInputSubmission.
func inputBody(v any, in *input, errs *[]httpx.FieldError) {
	loc := []any{"body"}
	o, ok := model(v, loc, errs)
	if !ok {
		return
	}
	in.submission.InputRequestID = required(o, "input_request_id", 1, 128, loc, errs)
	in.submission.Answers = wirejson.Object{}
	if a, present := o.Get("answers"); present {
		if obj, isObj := a.(wirejson.Object); isObj {
			in.submission.Answers = obj
		} else {
			*errs = append(*errs, httpx.DictType(at(loc, "answers")...))
		}
	}
	if sv, present := o.Get("secrets"); present {
		obj, isObj := sv.(wirejson.Object)
		if !isObj {
			*errs = append(*errs, httpx.DictType(at(loc, "secrets")...))
		}
		for _, m := range obj {
			l := at(at(loc, "secrets"), m.Key)
			switch x := m.Value.(type) {
			case string:
				in.submission.Secrets = append(in.submission.Secrets, service.SecretField{Field: m.Key, Answer: service.SecretAnswer{Value: x}})
			case wirejson.Object:
				ml := at(l, "InputSecretValue")
				value := required(x, "value", 1, 0, ml, errs)
				name, _ := str(x, "secret_name", 0, 256, true, ml, errs)
				extraForbidden(x, []string{"value", "secret_name"}, ml, errs)
				in.submission.Secrets = append(in.submission.Secrets, service.SecretField{Field: m.Key, Answer: service.SecretAnswer{Value: value, Name: name}})
			default:
				*errs = append(*errs, httpx.StringType(at(l, "str")...))
				*errs = append(*errs, httpx.FieldError{
					Type: "model_type", Loc: at(l, "InputSecretValue"),
					Msg: "Input should be a valid dictionary or instance of InputSecretValue",
					Ctx: wirejson.Object{{Key: "class_name", Value: "InputSecretValue"}},
				})
			}
		}
	}
	extraForbidden(o, []string{"input_request_id", "answers", "secrets"}, loc, errs)
}

// commandBody is TaskCommandPayload (extra keys ignored).
func commandBody(v any, in *input, errs *[]httpx.FieldError) {
	loc := []any{"body"}
	o, ok := model(v, loc, errs)
	if !ok {
		return
	}
	in.command.Command = required(o, "command", 0, 0, loc, errs)
	in.command.ModelInstanceID, _ = str(o, "model_instance_id", 0, 0, true, loc, errs)
	if b, present := o.Get("budget_usd"); present && b != nil {
		d, err := moneyOf(b)
		if err != nil {
			*errs = append(*errs, httpx.ValueError(err.Error(), at(loc, "budget_usd")...))
		} else {
			in.command.BudgetUSD = &d
		}
	}
	in.command.Message, _ = str(o, "message", 0, 0, true, loc, errs)
	in.command.MessageID, _ = str(o, "message_id", 0, 0, true, loc, errs)
}

type notMoney string

func (e notMoney) Error() string { return string(e) + " is not a money amount" }

// moneyOf is _parse_money over a JSON value.
func moneyOf(v any) (money.Decimal, error) {
	var text, repr string
	switch x := v.(type) {
	case bool:
		if x {
			return money.Decimal{}, notMoney("True")
		}
		return money.Decimal{}, notMoney("False")
	case string:
		text, repr = strings.TrimSpace(x), domain.PyStrRepr(x)
	case json.Number:
		text, repr = x.String(), x.String()
	case wirejson.Float:
		text = wirejson.FormatFloat(float64(x))
		repr = text
	default:
		b, _ := wirejson.Marshal(v, wirejson.Dumps)
		return money.Decimal{}, notMoney(string(b))
	}
	d, err := money.Parse(text)
	if err != nil {
		return money.Decimal{}, notMoney(repr)
	}
	return d, nil
}

// resolutionBody is EscalationResolution (extra keys ignored).
func resolutionBody(v any, in *input, errs *[]httpx.FieldError) {
	loc := []any{"body"}
	o, ok := model(v, loc, errs)
	if !ok {
		return
	}
	in.resolution.EscalationID = required(o, "escalation_id", 0, 0, loc, errs)
	in.resolution.Approved, _ = boolean(o, "approved", loc, errs)
	if c, _ := str(o, "comment", 0, 0, false, loc, errs); c != nil {
		in.resolution.Comment = *c
	}
}

// decisionBody is ToolCallApprovalDecision.
func decisionBody(v any, in *input, errs *[]httpx.FieldError) {
	loc := []any{"body"}
	o, ok := model(v, loc, errs)
	if !ok {
		return
	}
	in.approved, _ = boolean(o, "approved", loc, errs)
	in.comment, _ = str(o, "comment", 0, 2000, true, loc, errs)
	extraForbidden(o, []string{"approved", "comment"}, loc, errs)
}
