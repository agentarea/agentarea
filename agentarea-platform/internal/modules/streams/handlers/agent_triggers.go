package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"math"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

// AgentTriggers is api.AgentTriggers over the streams service.
type AgentTriggers struct {
	svc *service.Service
	log *slog.Logger
}

var _ api.AgentTriggers = AgentTriggers{}

// NewAgentTriggers builds the trigger creation that agent creation calls.
func NewAgentTriggers(svc *service.Service, log *slog.Logger) AgentTriggers {
	if log == nil {
		log = slog.Default()
	}
	return AgentTriggers{svc: svc, log: log}
}

// Check is the schema validation of every TriggerSpec, then validate_configuration of each in order.
func (a AgentTriggers) Check(ctx context.Context, c authn.Caller, specs []json.RawMessage) error {
	triggers, err := decodeSpecs(specs)
	if err != nil {
		return err
	}
	ctx = authn.WithCaller(ctx, c)
	for _, n := range triggers {
		if err := a.svc.CheckNew(ctx, c, n); err != nil {
			return specRefusal(err, "Trigger "+pyRepr(n.Name)+": ")
		}
	}
	return nil
}

// Create makes each spec a trigger of agentID; a failure deletes the ones already made.
func (a AgentTriggers) Create(ctx context.Context, c authn.Caller, agentID string, specs []json.RawMessage) error {
	triggers, err := decodeSpecs(specs)
	if err != nil {
		return err
	}
	ctx = authn.WithCaller(ctx, c)
	var made []string
	for _, n := range triggers {
		n.AgentID = agentID
		t, err := a.svc.Create(ctx, n)
		if err != nil {
			a.log.ErrorContext(ctx, "creating the triggers of a new agent failed", "agent_id", agentID, "error", err)
			undo := context.WithoutCancel(ctx)
			for i := len(made) - 1; i >= 0; i-- {
				if derr := a.svc.Delete(undo, made[i]); derr != nil {
					a.log.ErrorContext(ctx, "could not remove a trigger of an agent that was not created", "trigger_id", made[i], "error", derr)
				}
			}
			return specRefusal(err, "")
		}
		made = append(made, t.ID)
	}
	return nil
}

// specRefusal renders a service error as the agent route answers it: a configuration error is a 400
// with prefix before its message.
func specRefusal(err error, prefix string) error {
	var inv *domain.ValidationError
	if errors.As(err, &inv) {
		return httpx.BadRequest(prefix + inv.Error())
	}
	if he, ok := MapError(err); ok {
		return he
	}
	return err
}

// pyRepr is repr() of a str.
func pyRepr(s string) string {
	q := "'"
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		q = `"`
	}
	var b strings.Builder
	b.WriteString(q)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case string(r) == q:
			b.WriteString(`\` + q)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteString(q)
	return b.String()
}

func specFields() []string {
	return []string{
		"name", "description", "trigger_type", "task_parameters", "task_definition_id", "conditions", "enabled",
		"failure_threshold", "cron_expression", "timezone", "stream_id", "event_filter", "session", "batch",
	}
}

// decodeSpecs reads every spec as TriggerSpec, answering one 422 for all the schema errors.
func decodeSpecs(specs []json.RawMessage) ([]domain.NewTrigger, error) {
	var errs []httpx.FieldError
	out := make([]domain.NewTrigger, 0, len(specs))
	for i, raw := range specs {
		n, ok := decodeSpec(raw, i, &errs)
		if ok {
			out = append(out, n)
		}
	}
	if len(errs) > 0 {
		return nil, httpx.Validation(errs...)
	}
	return out, nil
}

func decodeSpec(raw json.RawMessage, i int, errs *[]httpx.FieldError) (domain.NewTrigger, bool) {
	at := func(rest ...any) []any { return append([]any{"body", "triggers", i}, rest...) }
	v, err := wirejson.Unmarshal(raw)
	o, isObj := v.(wirejson.Object)
	if err != nil || !isObj {
		*errs = append(*errs, httpx.ModelAttributesType(at()...))
		return domain.NewTrigger{}, false
	}
	var plain map[string]json.RawMessage
	if err := json.Unmarshal(raw, &plain); err != nil {
		*errs = append(*errs, httpx.ModelAttributesType(at()...))
		return domain.NewTrigger{}, false
	}
	before := len(*errs)
	n := domain.NewTrigger{Enabled: true, FailureThreshold: 5}
	tz := "UTC"
	n.Timezone = &tz
	dict := func(key string, nullable bool) map[string]any {
		val, ok := o.Get(key)
		if !ok || (val == nil && nullable) {
			return nil
		}
		if _, isDict := val.(wirejson.Object); !isDict {
			*errs = append(*errs, httpx.DictType(at(key)...))
			return nil
		}
		var m map[string]any
		_ = json.Unmarshal(plain[key], &m)
		return m
	}

	if s, ok := specString(o, "name", errs, at); ok {
		switch l := utf8.RuneCountInString(s); {
		case l < 1:
			*errs = append(*errs, httpx.StringTooShort(1, at("name")...))
		case l > 255:
			*errs = append(*errs, httpx.StringTooLong(255, at("name")...))
		default:
			n.Name = s
		}
	} else if _, set := o.Get("name"); !set {
		*errs = append(*errs, httpx.Missing(at("name")...))
	}
	if s, ok := specString(o, "description", errs, at); ok {
		if utf8.RuneCountInString(s) > 1000 {
			*errs = append(*errs, httpx.StringTooLong(1000, at("description")...))
		}
		n.Description = s
	}
	specTriggerType(o, &n, errs, at)
	if tp := dict("task_parameters", false); tp != nil || len(plain["task_parameters"]) > 0 {
		if tp == nil {
			tp = map[string]any{}
		}
		if msg := checkTaskParameters(tp); msg != "" && isDictField(o, "task_parameters") {
			*errs = append(*errs, httpx.ValueError(msg, at("task_parameters")...))
		}
		n.TaskParameters = tp
	} else {
		n.TaskParameters = map[string]any{}
	}
	if val, ok := o.Get("task_definition_id"); ok && val != nil {
		s, isStr := val.(string)
		if !isStr {
			*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: at("task_definition_id"), Msg: "UUID input should be a string, bytes or UUID object"})
		} else if id, fe := httpx.ValidateUUID(s, at("task_definition_id")...); fe != nil {
			*errs = append(*errs, *fe)
		} else {
			n.TaskDefinitionID = &id
		}
	}
	if n.Conditions = dict("conditions", false); n.Conditions == nil {
		n.Conditions = map[string]any{}
	}
	if val, ok := o.Get("enabled"); ok {
		if b, good := specBool(val, at("enabled"), errs); good {
			n.Enabled = b
		}
	}
	if val, ok := o.Get("failure_threshold"); ok {
		if k, good := specInt(val, at("failure_threshold"), errs); good {
			switch {
			case k < 1:
				*errs = append(*errs, httpx.GreaterThanEqual(1, at("failure_threshold")...))
			case k > 100:
				*errs = append(*errs, httpx.LessThanEqual(100, at("failure_threshold")...))
			default:
				n.FailureThreshold = int(k)
			}
		}
	}
	if s, ok := specNullableString(o, "cron_expression", errs, at); ok && s != nil {
		n.CronExpression = s
	}
	if s, ok := specString(o, "timezone", errs, at); ok {
		n.Timezone = &s
	}
	if val, ok := o.Get("stream_id"); ok && val != nil {
		s, isStr := val.(string)
		if !isStr {
			*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: at("stream_id"), Msg: "UUID input should be a string, bytes or UUID object"})
		} else if id, fe := httpx.ValidateUUID(s, at("stream_id")...); fe != nil {
			*errs = append(*errs, *fe)
		} else {
			n.StreamID = &id
		}
	}
	n.EventFilter = dict("event_filter", true)
	specSession(o, &n, errs, at)
	specBatch(o, &n, errs, at)
	for _, m := range o {
		if !contains(specFields(), m.Key) {
			*errs = append(*errs, httpx.ExtraForbidden(at(m.Key)...))
		}
	}
	if len(*errs) > before {
		return n, false
	}
	switch {
	case n.Type == domain.TypeCron && (n.CronExpression == nil || *n.CronExpression == ""):
		*errs = append(*errs, httpx.ValueError("cron_expression is required when trigger_type is 'cron'", at()...))
	case n.Type == domain.TypeCron && n.Batch != nil:
		*errs = append(*errs, httpx.ValueError("only a stream trigger takes a batch", at()...))
	case n.Type == domain.TypeStream && n.StreamID == nil:
		*errs = append(*errs, httpx.ValueError("stream_id is required when trigger_type is 'stream'", at()...))
	}
	return n, len(*errs) == before
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func isDictField(o wirejson.Object, key string) bool {
	v, ok := o.Get(key)
	if !ok {
		return false
	}
	_, isDict := v.(wirejson.Object)
	return isDict
}

// specString reads a str field; ok is false when it is absent or refused (the refusal is recorded).
func specString(o wirejson.Object, key string, errs *[]httpx.FieldError, at func(...any) []any) (string, bool) {
	v, present := o.Get(key)
	if !present {
		return "", false
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.StringType(at(key)...))
		return "", false
	}
	return s, true
}

func specNullableString(o wirejson.Object, key string, errs *[]httpx.FieldError, at func(...any) []any) (*string, bool) {
	if v, present := o.Get(key); present && v == nil {
		return nil, true
	}
	s, ok := specString(o, key, errs, at)
	if !ok {
		return nil, false
	}
	return &s, true
}

func specBool(v any, loc []any, errs *[]httpx.FieldError) (bool, bool) {
	switch t := v.(type) {
	case bool:
		return t, true
	case string:
		if b, ok := httpx.ParseBool(t); ok {
			return b, true
		}
		*errs = append(*errs, httpx.BoolParsing(loc...))
	case json.Number:
		switch t {
		case "0":
			return false, true
		case "1":
			return true, true
		}
		*errs = append(*errs, httpx.BoolParsing(loc...))
	default:
		*errs = append(*errs, httpx.BoolType(loc...))
	}
	return false, false
}

func specInt(v any, loc []any, errs *[]httpx.FieldError) (int64, bool) {
	switch t := v.(type) {
	case json.Number:
		k, err := t.Int64()
		if err != nil {
			if strings.HasPrefix(string(t), "-") {
				return math.MinInt64, true
			}
			return math.MaxInt64, true
		}
		return k, true
	case wirejson.Float:
		if f := float64(t); f == math.Trunc(f) && !math.IsInf(f, 0) {
			return int64(f), true
		}
		*errs = append(*errs, httpx.IntFromFloat(loc...))
	case string:
		if k, ok := httpx.ParseInt(t); ok {
			return k.Value, true
		}
		*errs = append(*errs, httpx.IntParsing(loc...))
	default:
		*errs = append(*errs, httpx.IntType(loc...))
	}
	return 0, false
}

func specTriggerType(o wirejson.Object, n *domain.NewTrigger, errs *[]httpx.FieldError, at func(...any) []any) {
	loc := at("trigger_type")
	v, present := o.Get("trigger_type")
	if !present {
		*errs = append(*errs, httpx.Missing(loc...))
		return
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.LiteralError([]string{domain.TypeCron, domain.TypeStream}, loc...))
		return
	}
	switch low := strings.ToLower(s); low {
	case domain.TypeCron, domain.TypeStream:
		n.Type = low
	default:
		*errs = append(*errs, httpx.ValueError("Invalid trigger type: "+pyRepr(s)+". Must be one of: ['cron', 'stream']", loc...))
	}
}

var effortShape = regexp.MustCompile(`^[a-z][a-z_-]{0,15}$`)

func reservedParameters() []string {
	return []string{"delivery_address", "follow_up_message", "session", "trigger_event", "trigger_event_file"}
}

// checkTaskParameters is TriggerSpec's three task_parameters validators; it returns the first refusal.
func checkTaskParameters(p map[string]any) string {
	var names []string
	for _, k := range reservedParameters() {
		if _, ok := p[k]; ok {
			names = append(names, k)
		}
	}
	if len(names) > 0 {
		return strings.Join(names, ", ") + " is set by the trigger that received the event and cannot be supplied"
	}
	if v, ok := p["model_override"]; ok && v != nil && v != "" {
		s, isStr := v.(string)
		if !isStr {
			return "model_override must be a model instance id"
		}
		if _, err := uuid.Parse(s); err != nil {
			return "model_override must be a model instance id"
		}
	}
	effort := false
	if v, ok := p["reasoning_effort"]; ok && v != nil && v != "" {
		s, isStr := v.(string)
		if !isStr || !effortShape.MatchString(s) {
			return "reasoning_effort must be a level name such as low or high"
		}
		effort = true
	}
	if v, ok := p["reasoning_max_tokens"]; ok && v != nil {
		f, isNum := v.(float64)
		if !isNum || f != math.Trunc(f) || f <= 0 {
			return "reasoning_max_tokens must be a positive integer"
		}
		if f > math.MaxInt32 {
			return "reasoning_max_tokens must be at most 2147483647"
		}
		if effort {
			return "set reasoning_effort or reasoning_max_tokens, not both"
		}
	}
	return ""
}

func specSession(o wirejson.Object, n *domain.NewTrigger, errs *[]httpx.FieldError, at func(...any) []any) {
	v, present := o.Get("session")
	if !present || v == nil {
		return
	}
	so, isObj := v.(wirejson.Object)
	if !isObj {
		*errs = append(*errs, httpx.ModelAttributesType(at("session")...))
		return
	}
	var s domain.Session
	for _, key := range []string{"continue", "continue_"} {
		if cv, ok := so.Get(key); ok && cv != nil {
			if b, good := specBool(cv, at("session", key), errs); good {
				s.Continue = &b
			}
		}
	}
	if iv, ok := so.Get("idle_timeout"); ok && iv != nil {
		str, isStr := iv.(string)
		switch {
		case !isStr:
			*errs = append(*errs, httpx.StringType(at("session", "idle_timeout")...))
		case !regexp.MustCompile(`^[0-9]+[smhd]$`).MatchString(str):
			*errs = append(*errs, httpx.StringPatternMismatch(`^[0-9]+[smhd]$`, at("session", "idle_timeout")...))
		default:
			s.IdleTimeout = &str
		}
	}
	for _, m := range so {
		if m.Key != "continue" && m.Key != "continue_" && m.Key != "idle_timeout" {
			*errs = append(*errs, httpx.ExtraForbidden(at("session", m.Key)...))
		}
	}
	n.Session = &s
}

func specBatch(o wirejson.Object, n *domain.NewTrigger, errs *[]httpx.FieldError, at func(...any) []any) {
	v, present := o.Get("batch")
	if !present || v == nil {
		return
	}
	bo, isObj := v.(wirejson.Object)
	if !isObj {
		*errs = append(*errs, httpx.ModelAttributesType(at("batch")...))
		return
	}
	before := len(*errs)
	var b domain.Batch
	if wv, ok := bo.Get("window"); ok && wv != nil {
		str, isStr := wv.(string)
		switch {
		case !isStr:
			*errs = append(*errs, httpx.StringType(at("batch", "window")...))
		case !regexp.MustCompile(`^[1-9][0-9]*[smhd]$`).MatchString(str):
			*errs = append(*errs, httpx.StringPatternMismatch(`^[1-9][0-9]*[smhd]$`, at("batch", "window")...))
		default:
			b.Window = &str
		}
	}
	if mv, ok := bo.Get("max_events"); ok && mv != nil {
		if k, good := specInt(mv, at("batch", "max_events"), errs); good {
			if k < 2 {
				*errs = append(*errs, httpx.GreaterThanEqual(2, at("batch", "max_events")...))
			} else {
				m := int(min(k, math.MaxInt32))
				b.MaxEvents = &m
			}
		}
	}
	for _, m := range bo {
		if m.Key != "window" && m.Key != "max_events" {
			*errs = append(*errs, httpx.ExtraForbidden(at("batch", m.Key)...))
		}
	}
	if len(*errs) == before && b.Window == nil && b.MaxEvents == nil {
		*errs = append(*errs, httpx.ValueError("a batch needs a window or max_events", at("batch")...))
	}
	n.Batch = &b
}
