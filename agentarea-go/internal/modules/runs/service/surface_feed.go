package service

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

// feedRow is a task log row as the feed reads it (ConversationEntry).
type feedRow struct {
	Seq         int64
	EventID     string
	Kind, Role  string
	Content     string
	ToolCalls   any
	ToolCallID  string
	Name        string
	Attachments any
	Meta        wirejson.Object
	Iteration   any
	ExecutionID *string
	OccurredAt  *time.Time
	HasBodyRef  bool
}

func decodeJSON(raw string) (any, error) {
	if raw == "" {
		return nil, nil
	}
	return wirejson.Unmarshal([]byte(raw))
}

func feedRowOf(r store.SurfaceFeedAfterRow) (feedRow, error) {
	out := feedRow{
		Seq: int64(r.Seq), EventID: r.EventID.String(), Kind: r.Kind, Role: r.Role, Content: r.Content,
		ToolCallID: r.ToolCallID.String, Name: r.Name.String, ExecutionID: store.TextPtr(r.ExecutionID),
		OccurredAt: store.TimestamptzPtr(r.CreatedAt), HasBodyRef: r.BodyRef.Valid,
	}
	var err error
	if out.ToolCalls, err = decodeJSON(r.ToolCalls); err != nil {
		return out, fmt.Errorf("tool calls of row %d: %w", r.Seq, err)
	}
	if out.Attachments, err = decodeJSON(r.Attachments); err != nil {
		return out, fmt.Errorf("attachments of row %d: %w", r.Seq, err)
	}
	meta, err := decodeJSON(r.Meta)
	if err != nil {
		return out, fmt.Errorf("meta of row %d: %w", r.Seq, err)
	}
	out.Meta, _ = meta.(wirejson.Object)
	if r.Iteration.Valid {
		out.Iteration = int(r.Iteration.Int32)
	}
	return out, nil
}

// feedBodies is FeedBodies: a run's full tool arguments and results by call id.
type feedBodies struct {
	results   map[string]string
	arguments map[string]any
	revealed  bool
}

// bodiesOf is FeedBodies.of.
func bodiesOf(rows []feedRow, revealed bool) *feedBodies {
	b := &feedBodies{results: map[string]string{}, arguments: map[string]any{}, revealed: revealed}
	for _, r := range rows {
		if r.Kind != "message" {
			continue
		}
		if r.Role == "tool" && r.ToolCallID != "" && !r.HasBodyRef {
			b.results[r.ToolCallID] = r.Content
		}
		if r.Role != "assistant" {
			continue
		}
		calls, _ := r.ToolCalls.([]any)
		for _, call := range calls {
			obj, ok := call.(wirejson.Object)
			if !ok {
				continue
			}
			id, _ := obj.Get("id")
			fn, _ := obj.Get("function")
			idStr, _ := id.(string)
			fnObj, isObj := fn.(wirejson.Object)
			if idStr == "" || !isObj {
				continue
			}
			raw, _ := fnObj.Get("arguments")
			b.arguments[idStr] = parsedArguments(raw)
		}
	}
	return b
}

func parsedArguments(raw any) any {
	text, ok := raw.(string)
	if !ok {
		return raw
	}
	v, err := wirejson.Unmarshal([]byte(text))
	if err != nil {
		return text
	}
	return v
}

// feedEvent is feed_event: the row as (type, data), ok false for a row the feed leaves out.
func feedEvent(r feedRow, b *feedBodies) (string, wirejson.Object, bool, error) {
	if r.Kind == "event" {
		if r.Name == "" {
			return "", nil, false, fmt.Errorf("event row %d has no type", r.Seq)
		}
		data := append(wirejson.Object{}, r.Meta...)
		callValue, _ := data.Get("tool_call_id")
		callID, isStr := callValue.(string)
		if b != nil && isStr {
			if r.Name == domain.EventToolCall || r.Name == domain.EventToolResult {
				if args, ok := b.arguments[callID]; ok {
					if b.revealed {
						data.Set("arguments", revealToolValue(args, "", 0))
					} else {
						data.Set("arguments", sanitizeOrdered(args, "", 0))
					}
				}
			}
			if r.Name == domain.EventToolResult {
				if result, ok := b.results[callID]; ok {
					if b.revealed {
						data.Set("result", revealToolValue(result, "", 0))
					} else {
						data.Set("result", sanitizeOrdered(result, "result", 0))
					}
				}
			}
		}
		return r.Name, data, true, nil
	}
	if r.Kind == "message" && r.Role == "user" {
		attachments := r.Attachments
		if !truthy(attachments) {
			attachments = []any{}
		}
		data := wirejson.Object{
			{Key: "content", Value: r.Content}, {Key: "attachments", Value: attachments},
			{Key: "iteration", Value: r.Iteration}, {Key: "execution_id", Value: strOrNil(r.ExecutionID)},
		}
		if r.HasBodyRef {
			data = append(data, wirejson.Member{Key: "content_stored_separately", Value: true})
		}
		return domain.EventMessageReceived, data, true, nil
	}
	return "", nil, false, nil
}

type pgUUID = uuid.UUID

const redacted = "[redacted]"

const nestedOmitted = "[nested value omitted from event log]"

// nameVerdict is what sanitize_tool_event_value answers for a field name
// whatever its value: "[redacted]" or an omission; "" when the value decides.
func nameVerdict(field string) string {
	v, _ := domain.SanitizeToolEventValue(struct{}{}, field).(string)
	if v == "[redacted]" || strings.HasPrefix(v, "[omitted from event log") {
		return v
	}
	return ""
}

// sanitizeOrdered is sanitize_tool_event_value over values that keep their key order.
func sanitizeOrdered(value any, field string, depth int) any {
	if depth >= 10 {
		return nestedOmitted
	}
	switch v := value.(type) {
	case wirejson.Object:
		if verdict := nameVerdict(field); verdict != "" {
			return verdict
		}
		n := min(len(v), 100)
		out := make(wirejson.Object, n)
		for i := range n {
			out[i] = wirejson.Member{Key: v[i].Key, Value: sanitizeOrdered(v[i].Value, v[i].Key, depth+1)}
		}
		return out
	case []any:
		if verdict := nameVerdict(field); verdict != "" {
			return verdict
		}
		n := min(len(v), 100)
		out := make([]any, n)
		for i := range n {
			out[i] = sanitizeOrdered(v[i], "", depth+1)
		}
		return out
	case wirejson.Float:
		if verdict := nameVerdict(field); verdict != "" {
			return verdict
		}
		return v
	}
	return domain.SanitizeToolEventValue(value, field)
}

// secretName is redaction._secret_name.
// revealToolValue is reveal_tool_value: whole, secret-shaped keys and inline secrets masked.
func revealToolValue(value any, field string, depth int) any {
	if depth >= 10 {
		return nestedOmitted
	}
	if field != "" && domain.SecretName(field) {
		return redacted
	}
	switch v := value.(type) {
	case string:
		return domain.MaskInlineSecrets(v)
	case wirejson.Object:
		out := make(wirejson.Object, len(v))
		for i, m := range v {
			out[i] = wirejson.Member{Key: m.Key, Value: revealToolValue(m.Value, m.Key, depth+1)}
		}
		return out
	case []any:
		out := make([]any, len(v))
		for i, x := range v {
			out[i] = revealToolValue(x, "", depth+1)
		}
		return out
	case nil, bool, json.Number, wirejson.Float:
		return v
	}
	return fmt.Sprintf("[%T omitted from event log]", value)
}

// filterDomainFields is _filter_domain_fields.
func filterDomainFields(data wirejson.Object) wirejson.Object {
	if inner, ok := data.Get("data"); ok {
		if innerObj, isObj := inner.(wirejson.Object); isObj {
			out := wirejson.Object{}
			for _, m := range data {
				if m.Key != "data" {
					out = append(out, m)
				}
			}
			for _, m := range filterDomainFields(innerObj) {
				out.Set(m.Key, m.Value)
			}
			return out
		}
	}
	without := func(keys ...string) wirejson.Object {
		out := wirejson.Object{}
		for _, m := range data {
			skip := false
			for _, k := range keys {
				skip = skip || m.Key == k
			}
			if !skip {
				out = append(out, m)
			}
		}
		return out
	}
	if t, ok := data.Get("original_event_type"); ok {
		ts, _ := t.(string)
		orig, hasOrig := data.Get("original_data")
		origText := "{}"
		if hasOrig {
			origText = pyReprish(orig)
		}
		if strings.HasPrefix(ts, "ToolCall") || strings.HasPrefix(ts, "LLMCall") || strings.HasPrefix(ts, "A2UI") ||
			strings.Contains(origText, "tool_name") {
			if o, isObj := orig.(wirejson.Object); isObj || !hasOrig {
				out := without("original_event_type", "original_data", "aggregate_id", "aggregate_type")
				for _, m := range o {
					out.Set(m.Key, m.Value)
				}
				return out
			}
			return without("original_event_type")
		}
	}
	return without("original_event_type", "original_data")
}

// pyReprish is enough of str(value) to find a key name in it.
func pyReprish(v any) string {
	b, err := wirejson.Marshal(v, wirejson.Dumps)
	if err != nil {
		return fmt.Sprint(v)
	}
	return string(b)
}

// feedEventJSON is the TaskEvent the events page shows for a row.
func feedEventJSON(taskID, agentID string, r feedRow, eventType string, data wirejson.Object) (wirejson.Object, error) {
	if r.OccurredAt == nil {
		return nil, fmt.Errorf("task %s log row %d was read without its time", taskID, r.Seq)
	}
	execID := strOrNil(r.ExecutionID)
	if r.ExecutionID == nil || *r.ExecutionID == "" {
		execID, _ = data.Get("execution_id")
	}
	message, _ := data.Get("message")
	return wirejson.Object{
		{Key: "id", Value: r.EventID},
		{Key: "task_id", Value: taskID},
		{Key: "agent_id", Value: agentID},
		{Key: "execution_id", Value: execID},
		{Key: "timestamp", Value: PyISO(*r.OccurredAt, true)},
		{Key: "event_type", Value: eventType},
		{Key: "message", Value: message},
		{Key: "event_id", Value: r.EventID},
		{Key: "seq", Value: r.Seq},
		{Key: "data", Value: filterDomainFields(data)},
		{Key: "metadata", Value: data},
	}, nil
}

// readBodies is TaskFeedReader.bodies.
func readBodies(ctx context.Context, q *store.Queries, ws scope.Workspace, taskID pgUUID, rows []feedRow, revealed bool) (*feedBodies, error) {
	ids := []string{}
	seen := map[string]bool{}
	for _, r := range rows {
		if r.Kind != "event" || (r.Name != domain.EventToolCall && r.Name != domain.EventToolResult) {
			continue
		}
		v, _ := r.Meta.Get("tool_call_id")
		if id, ok := v.(string); ok && !seen[id] {
			seen[id] = true
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return &feedBodies{results: map[string]string{}, arguments: map[string]any{}}, nil
	}
	got, err := q.SurfaceFeedBodies(ctx, store.SurfaceFeedBodiesParams{TaskID: taskID, WorkspaceID: ws.ID(), CallIds: ids})
	if err != nil {
		return nil, err
	}
	body := make([]feedRow, len(got))
	for i, g := range got {
		if body[i], err = feedRowOf(store.SurfaceFeedAfterRow(g)); err != nil {
			return nil, err
		}
	}
	return bodiesOf(body, revealed), nil
}

// EventsPage is get_task_events.
func (s *Surface) EventsPage(ctx context.Context, agentID, taskID string, page, pageSize int, eventType *string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil {
		return nil, err
	}
	if !ok || t.AgentID != agentID {
		return nil, notFound("Task not found")
	}
	out, err := s.eventsPage(ctx, c.Workspace, t, page, pageSize, eventType, func() (bool, error) { return s.mayAct(ctx, c, t) })
	if err != nil {
		return nil, s.internal(ctx, "Failed to get task events", err)
	}
	return out, nil
}

func (s *Surface) eventsPage(ctx context.Context, ws scope.Workspace, t Task, page, pageSize int, eventType *string, mayAct func() (bool, error)) (wirejson.Object, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	q := store.New(sess.Q())
	id, _ := parseID(t.ID)
	typ := store.Text(nil)
	if eventType != nil && *eventType != "" {
		typ = store.Text(eventType)
	}
	total, err := q.SurfaceFeedCount(ctx, store.SurfaceFeedCountParams{TaskID: id, WorkspaceID: ws.ID(), EventType: typ})
	if err != nil {
		return nil, err
	}
	got, err := q.SurfaceFeedPage(ctx, store.SurfaceFeedPageParams{
		TaskID: id, WorkspaceID: ws.ID(), EventType: typ, Skip: int32((page - 1) * pageSize), MaxRows: int32(pageSize),
	})
	if err != nil {
		return nil, err
	}
	rows := make([]feedRow, len(got))
	showsTools := false
	for i, g := range got {
		if rows[i], err = feedRowOf(store.SurfaceFeedAfterRow(g)); err != nil {
			return nil, err
		}
		showsTools = showsTools || rows[i].Name == domain.EventToolCall || rows[i].Name == domain.EventToolResult
	}
	revealed := false
	if showsTools {
		if revealed, err = mayAct(); err != nil {
			return nil, err
		}
	}
	bodies, err := readBodies(ctx, q, ws, id, rows, revealed)
	if err != nil {
		return nil, err
	}
	items := []any{}
	for _, r := range rows {
		typ, data, ok, err := feedEvent(r, bodies)
		if err != nil {
			return nil, err
		}
		if !ok {
			continue
		}
		item, err := feedEventJSON(t.ID, t.AgentID, r, typ, data)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return wirejson.Object{
		{Key: "events", Value: items}, {Key: "total", Value: total}, {Key: "page", Value: page},
		{Key: "page_size", Value: pageSize}, {Key: "has_next", Value: int64(page)*int64(pageSize) < total},
	}, nil
}

// feedAt is TaskFeedReader.at: the feed row at seq, ok false when there is none.
func feedAt(ctx context.Context, sess db.Session, taskID pgUUID, seq int64) (feedRow, bool, error) {
	r, err := store.New(sess.Q()).SurfaceFeedAt(ctx, store.SurfaceFeedAtParams{TaskID: taskID, WorkspaceID: sess.Workspace().ID(), Seq: int32(seq)})
	if store.NoRows(err) {
		return feedRow{}, false, nil
	}
	if err != nil {
		return feedRow{}, false, err
	}
	row, err := feedRowOf(store.SurfaceFeedAfterRow(r))
	return row, err == nil, err
}
