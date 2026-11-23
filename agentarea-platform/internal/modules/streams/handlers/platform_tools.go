package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/streams"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
)

// toolRefusal is a refusal in the words the toolset reports.
type toolRefusal string

func (r toolRefusal) Error() string { return string(r) }

// toolText is err as a platform tool reports it: the detail its REST route answers.
func toolText(err error) error {
	if err == nil {
		return nil
	}
	if he, ok := MapError(err); ok {
		return he
	}
	return err
}

func mustUUID(param, id string) error {
	if _, err := uuid.Parse(id); err != nil {
		return fmt.Errorf("%s must be a UUID", param)
	}
	return nil
}

func lengthError(field string, s string, lo, hi int) error {
	n := utf8.RuneCountInString(s)
	if n < lo {
		return fmt.Errorf("%s: String should have at least %d character", field, lo)
	}
	if hi > 0 && n > hi {
		return fmt.Errorf("%s: String should have at most %d characters", field, hi)
	}
	return nil
}

// PlatformTriggers is api.PlatformTriggers over the streams service.
type PlatformTriggers struct{ svc *service.Service }

var _ api.PlatformTriggers = PlatformTriggers{}

// NewPlatformTriggers builds the triggers toolset's provider.
func NewPlatformTriggers(svc *service.Service) PlatformTriggers { return PlatformTriggers{svc: svc} }

// triggerSummary is _trigger_summary: the stream fields come from its subscription.
func triggerSummary(t domain.Trigger) api.TriggerView {
	out := api.TriggerView{
		ID: t.ID, Name: t.Name, Description: t.Description, AgentID: t.AgentID, TaskDefinitionID: t.TaskDefinitionID,
		TriggerType: t.Type, IsActive: t.IsActive, CronExpression: t.CronExpression, Status: t.Status(),
	}
	out.NeedsNewOwner = out.Status == domain.StatusNeedsOwner
	if t.Session != nil {
		out.Session = t.Session
	}
	if t.Batch != nil {
		out.Batch = t.Batch
	}
	if b := t.Binding; b != nil {
		sid := b.StreamID
		out.StreamID = &sid
		out.EventFilter = b.Filter
		if out.EventFilter == nil {
			out.EventFilter = map[string]any{}
		}
		out.LastEventAt = b.LastEventAt
	}
	return out
}

func (p PlatformTriggers) List(ctx context.Context, c authn.Caller, agentID string, activeOnly bool, limit int) ([]api.TriggerView, error) {
	ctx = authn.WithCaller(ctx, c)
	f := store.Filter{ActiveOnly: activeOnly, Limit: int32(max(limit, 0))} //nolint:gosec // bounded by the tool
	if agentID != "" {
		if err := mustUUID("agent_id", agentID); err != nil {
			return nil, err
		}
		f.AgentID = &agentID
	}
	ts, err := p.svc.List(ctx, f)
	if err != nil {
		return nil, toolText(err)
	}
	out := make([]api.TriggerView, len(ts))
	for i, t := range ts {
		out[i] = triggerSummary(t)
	}
	return out, nil
}

func (p PlatformTriggers) Get(ctx context.Context, c authn.Caller, triggerID string) (api.TriggerView, error) {
	t, err := p.svc.Get(authn.WithCaller(ctx, c), triggerID)
	if errors.Is(err, domain.ErrNotFound) {
		return api.TriggerView{}, api.ErrTriggerNotFound
	}
	if err != nil {
		return api.TriggerView{}, toolText(err)
	}
	return triggerSummary(t), nil
}

// documentInto reads a session or batch document as model_validate would.
func documentInto[T any](field string, doc map[string]any) (*T, error) {
	if len(doc) == 0 {
		return nil, nil
	}
	raw, err := json.Marshal(doc)
	if err != nil {
		return nil, err
	}
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	var v T
	if err := dec.Decode(&v); err != nil {
		return nil, fmt.Errorf("%s: %s", field, err.Error())
	}
	return &v, nil
}

// triggerCreate is TriggerCreate's validation of the toolset's arguments.
func triggerCreate(in api.TriggerCreate) (domain.NewTrigger, error) {
	n := domain.NewTrigger{
		Name: in.Name, Description: in.Description, AgentID: in.AgentID, Type: in.Type, StreamID: in.StreamID,
		EventFilter: in.EventFilter, TaskParameters: in.TaskParameters, TaskDefinitionID: in.TaskDefinitionID,
		Conditions: in.Conditions, Enabled: in.Enabled, FailureThreshold: in.FailureThreshold,
		CronExpression: in.CronExpression, Timezone: in.Timezone,
	}
	if err := lengthError("name", in.Name, 1, 255); err != nil {
		return n, err
	}
	if utf8.RuneCountInString(in.Description) > 1000 {
		return n, errors.New("description: String should have at most 1000 characters")
	}
	if in.FailureThreshold < 1 || in.FailureThreshold > 100 {
		return n, errors.New("failure_threshold: Input should be between 1 and 100")
	}
	if err := mustUUID("agent_id", in.AgentID); err != nil {
		return n, err
	}
	if in.TaskDefinitionID != nil {
		if err := mustUUID("task_definition_id", *in.TaskDefinitionID); err != nil {
			return n, err
		}
	}
	if n.TaskParameters == nil {
		n.TaskParameters = map[string]any{}
	}
	if n.Conditions == nil {
		n.Conditions = map[string]any{}
	}
	var err error
	if n.Session, err = documentInto[domain.Session]("session", in.Session); err != nil {
		return n, err
	}
	if n.Batch, err = documentInto[domain.Batch]("batch", in.Batch); err != nil {
		return n, err
	}
	return n, nil
}

func (p PlatformTriggers) Create(ctx context.Context, c authn.Caller, in api.TriggerCreate) (api.TriggerView, error) {
	ctx = authn.WithCaller(ctx, c)
	if in.StreamID != nil {
		if err := mustUUID("stream_id", *in.StreamID); err != nil {
			return api.TriggerView{}, err
		}
		if err := p.svc.RequireStream(ctx, "read", *in.StreamID); err != nil {
			return api.TriggerView{}, toolText(err)
		}
	}
	n, err := triggerCreate(in)
	if err != nil {
		return api.TriggerView{}, err
	}
	t, err := p.svc.Create(ctx, n)
	if err != nil {
		return api.TriggerView{}, toolText(err)
	}
	return triggerSummary(t), nil
}

// existed is false for a trigger that does not exist, the error otherwise.
func existed(err error) (bool, error) {
	if errors.Is(err, domain.ErrNotFound) {
		return false, nil
	}
	if err != nil {
		return false, toolText(err)
	}
	return true, nil
}

func (p PlatformTriggers) Delete(ctx context.Context, c authn.Caller, triggerID string) (bool, error) {
	if err := mustUUID("trigger_id", triggerID); err != nil {
		return false, err
	}
	return existed(p.svc.Delete(authn.WithCaller(ctx, c), triggerID))
}

func (p PlatformTriggers) Enable(ctx context.Context, c authn.Caller, triggerID string) (bool, error) {
	if err := mustUUID("trigger_id", triggerID); err != nil {
		return false, err
	}
	_, err := p.svc.Enable(authn.WithCaller(ctx, c), triggerID)
	return existed(err)
}

func (p PlatformTriggers) Disable(ctx context.Context, c authn.Caller, triggerID string) (bool, error) {
	if err := mustUUID("trigger_id", triggerID); err != nil {
		return false, err
	}
	_, err := p.svc.Disable(authn.WithCaller(ctx, c), triggerID)
	return existed(err)
}

// isoformat is datetime.isoformat() in UTC.
func isoformat(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 != 0 {
		return t.Format("2006-01-02T15:04:05.000000-07:00")
	}
	return t.Format("2006-01-02T15:04:05-07:00")
}

func (p PlatformTriggers) History(ctx context.Context, c authn.Caller, triggerID string, limit, offset int) ([]api.TriggerExecution, error) {
	rows, err := p.svc.ExecutionHistory(authn.WithCaller(ctx, c), triggerID, limit, offset)
	if err != nil {
		return nil, toolText(err)
	}
	out := make([]api.TriggerExecution, len(rows))
	for i, e := range rows {
		out[i] = api.TriggerExecution{ID: e.ID, Status: e.Status, ExecutionTimeMs: e.ExecutionTimeMs, ErrorMessage: e.ErrorMessage, TaskID: e.TaskID}
		if !e.ExecutedAt.IsZero() {
			at := isoformat(e.ExecutedAt)
			out[i].ExecutedAt = &at
		}
	}
	return out, nil
}

// PlatformStreams is api.PlatformStreams over the streams service, answering
// what the REST routes answer.
type PlatformStreams struct{ s *Server }

var _ api.PlatformStreams = PlatformStreams{}

// NewPlatformStreams builds the streams toolset's provider.
func NewPlatformStreams(svc *service.Service, log *slog.Logger) PlatformStreams {
	return PlatformStreams{s: New(svc, nil, log)}
}

// require is @requires(permission, "stream", id_param="stream_id").
func (p PlatformStreams) require(ctx context.Context, permission, streamID string) error {
	if err := mustUUID("stream_id", streamID); err != nil {
		return err
	}
	return toolText(p.s.svc.RequireStream(ctx, permission, streamID))
}

var errSourcesUnavailable = errors.New("stream sources need the catalog's source types and the secret stores, which this process was not given")

func (p PlatformStreams) List(ctx context.Context, c authn.Caller, limit, offset int) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	rows, err := p.s.svc.ListStreams(ctx, limit, offset)
	if err == nil {
		err = p.s.svc.WithSourceTypes(ctx, rows)
	}
	if err != nil {
		return nil, toolText(err)
	}
	out := make([]streamJSON, len(rows))
	for i, r := range rows {
		out[i] = streamOut(r)
	}
	return out, nil
}

func (p PlatformStreams) Get(ctx context.Context, c authn.Caller, streamID string) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "read", streamID); err != nil {
		return nil, err
	}
	st, err := p.s.svc.GetStream(ctx, streamID)
	one := []domain.Stream{st}
	if err == nil {
		err = p.s.svc.WithSourceTypes(ctx, one)
	}
	if err != nil {
		return nil, toolText(err)
	}
	return streamOut(one[0]), nil
}

func (p PlatformStreams) Create(ctx context.Context, c authn.Caller, name, description string) (any, error) {
	if err := lengthError("name", name, 1, 255); err != nil {
		return nil, err
	}
	if utf8.RuneCountInString(description) > 1000 {
		return nil, errors.New("description: String should have at most 1000 characters")
	}
	st, err := p.s.svc.CreateStream(authn.WithCaller(ctx, c), name, description)
	if err != nil {
		return nil, toolText(err)
	}
	return streamOut(st), nil
}

func (p PlatformStreams) Delete(ctx context.Context, c authn.Caller, streamID string) error {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "delete", streamID); err != nil {
		return err
	}
	return toolText(p.s.svc.DeleteStream(ctx, streamID))
}

func (p PlatformStreams) ListSourceTypes(ctx context.Context, c authn.Caller) (any, error) {
	if !p.s.svc.SourcesReady() {
		return nil, errSourcesUnavailable
	}
	entries, err := p.s.svc.SourceTypeEntries(authn.WithCaller(ctx, c))
	if err != nil {
		return nil, toolText(err)
	}
	out := make([]sourceTypeJSON, 0, len(entries))
	for _, e := range entries {
		out = append(out, p.s.sourceTypeOut(e))
	}
	return out, nil
}

func (p PlatformStreams) ListSources(ctx context.Context, c authn.Caller, streamID string) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "read", streamID); err != nil {
		return nil, err
	}
	rows, err := p.s.svc.ListSources(ctx, streamID)
	if err != nil {
		return nil, toolText(err)
	}
	out := make([]sourceJSON, 0, len(rows))
	for _, r := range rows {
		out = append(out, p.s.sourceOut(r))
	}
	return out, nil
}

func (p PlatformStreams) CreateSource(ctx context.Context, c authn.Caller, streamID string, source []byte) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "edit", streamID); err != nil {
		return nil, err
	}
	if !p.s.svc.SourcesReady() {
		return nil, errSourcesUnavailable
	}
	var b gen.SourceCreate
	if err := json.Unmarshal(source, &b); err != nil {
		return nil, toolRefusal("Invalid arguments: " + err.Error())
	}
	n, err := newSource(&b)
	if err != nil {
		return nil, err
	}
	src, issued, err := p.s.svc.AddSource(ctx, streamID, n)
	if err != nil {
		return nil, toolText(sourceError(err))
	}
	return sourceCreatedJSON{sourceJSON: p.s.sourceOut(src), Issued: issued}, nil
}

func (p PlatformStreams) UpdateSource(ctx context.Context, c authn.Caller, streamID, sourceID string, senders []byte) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "edit", streamID); err != nil {
		return nil, err
	}
	if !p.s.svc.SourcesReady() {
		return nil, errSourcesUnavailable
	}
	var g gen.Senders
	if err := json.Unmarshal(senders, &g); err != nil {
		return nil, fmt.Errorf("senders: %s", err.Error())
	}
	sd, err := sendersOf(g)
	if err != nil {
		return nil, err
	}
	src, err := p.s.svc.SetSourceSenders(ctx, streamID, sourceID, sd)
	if err != nil {
		return nil, toolText(sourceError(err))
	}
	return p.s.sourceOut(src), nil
}

func (p PlatformStreams) DeleteSource(ctx context.Context, c authn.Caller, streamID, sourceID string) error {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "edit", streamID); err != nil {
		return err
	}
	if !p.s.svc.SourcesReady() {
		return errSourcesUnavailable
	}
	return toolText(sourceError(p.s.svc.DeleteSource(ctx, streamID, sourceID)))
}

func (p PlatformStreams) ListSubscriptions(ctx context.Context, c authn.Caller, streamID string) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "read", streamID); err != nil {
		return nil, err
	}
	rows, err := p.s.svc.ListSubscriptions(ctx, streamID)
	if err != nil {
		return nil, toolText(err)
	}
	out := make([]subscriptionJSON, len(rows))
	for i, r := range rows {
		out[i] = subscriptionOut(r)
	}
	return out, nil
}

// filterOf is EventFilter.model_validate(event_filter or {}).
func filterOf(f map[string]any) (domain.EventFilter, error) {
	if f == nil {
		return domain.ParseEventFilter(nil)
	}
	out, err := domain.ParseEventFilter(f)
	return out, toolText(err)
}

const outputsTooShort = "output_stream_ids: List should have at least 1 item after validation, not 0"

func (p PlatformStreams) CreateForward(ctx context.Context, c authn.Caller, streamID string, outputs []string, eventFilter map[string]any) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "edit", streamID); err != nil {
		return nil, err
	}
	if len(outputs) == 0 {
		return nil, errors.New(outputsTooShort)
	}
	f, err := filterOf(eventFilter)
	if err != nil {
		return nil, err
	}
	sub, err := p.s.svc.CreateForward(ctx, streamID, outputs, f)
	if err != nil {
		return nil, toolText(err)
	}
	return subscriptionOut(sub), nil
}

func (p PlatformStreams) DeleteForward(ctx context.Context, c authn.Caller, streamID, subscriptionID string) error {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "edit", streamID); err != nil {
		return err
	}
	return toolText(p.s.svc.DeleteForward(ctx, streamID, subscriptionID))
}

func (p PlatformStreams) CreateProcessor(ctx context.Context, c authn.Caller, streamID string, outputs []string, code string, eventFilter map[string]any) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "edit", streamID); err != nil {
		return nil, err
	}
	if len(outputs) == 0 {
		return nil, errors.New(outputsTooShort)
	}
	if code == "" {
		return nil, errors.New("code: String should have at least 1 character")
	}
	f, err := filterOf(eventFilter)
	if err != nil {
		return nil, err
	}
	sub, err := p.s.svc.CreateProcessor(ctx, streamID, outputs, code, f)
	if err != nil {
		return nil, toolText(err)
	}
	return subscriptionOut(sub), nil
}

func (p PlatformStreams) UpdateProcessor(ctx context.Context, c authn.Caller, streamID, subscriptionID string, ch api.ProcessorChange) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "edit", streamID); err != nil {
		return nil, err
	}
	patch := service.ProcessorPatch{Code: ch.Code, Outputs: ch.Outputs}
	if ch.Outputs != nil && len(ch.Outputs) == 0 {
		return nil, errors.New(outputsTooShort)
	}
	if ch.Code != nil && *ch.Code == "" {
		return nil, errors.New("code: String should have at least 1 character")
	}
	if ch.EventFilter != nil {
		f, err := filterOf(ch.EventFilter)
		if err != nil {
			return nil, err
		}
		patch.Filter = &f
	}
	sub, err := p.s.svc.UpdateProcessor(ctx, streamID, subscriptionID, patch)
	if err != nil {
		return nil, toolText(err)
	}
	return subscriptionOut(sub), nil
}

func (p PlatformStreams) DeleteProcessor(ctx context.Context, c authn.Caller, streamID, subscriptionID string) error {
	ctx = authn.WithCaller(ctx, c)
	if err := p.require(ctx, "edit", streamID); err != nil {
		return err
	}
	return toolText(p.s.svc.DeleteProcessor(ctx, streamID, subscriptionID))
}

// ListEvents is one stream after a sequence when only stream_id is given,
// otherwise the workspace feed of the streams the caller may read.
func (p PlatformStreams) ListEvents(ctx context.Context, c authn.Caller, q api.EventQuery) (any, error) {
	ctx = authn.WithCaller(ctx, c)
	if q.StreamID != nil {
		if _, err := uuid.Parse(*q.StreamID); err != nil {
			return nil, errors.New("stream_id: Input should be a valid UUID")
		}
	}
	if q.Result != nil && !slices.Contains(domain.ProcessingStatuses(), *q.Result) {
		quoted := make([]string, 0, 6)
		for _, s := range domain.ProcessingStatuses() {
			quoted = append(quoted, "'"+s+"'")
		}
		return nil, fmt.Errorf("result: Input should be %s or %s", strings.Join(quoted[:len(quoted)-1], ", "), quoted[len(quoted)-1])
	}
	streamOnly := q.SourceType == nil && q.Kind == nil && q.Sender == nil && q.SessionKey == nil && q.Result == nil &&
		q.Since == nil && q.Until == nil && q.Before == nil
	if q.StreamID == nil || !streamOnly {
		if q.Before != nil && *q.Before < 1 {
			return nil, fmt.Errorf("before must be at least 1, got %d", *q.Before)
		}
		f := domain.FeedFilter{StreamID: q.StreamID, SourceType: q.SourceType, Kind: q.Kind, Sender: q.Sender,
			SessionKey: q.SessionKey, Result: q.Result, Since: q.Since, Until: q.Until, Platform: true}
		page, err := p.s.svc.WorkspaceFeed(ctx, f, q.Before, q.Limit)
		if err != nil {
			return nil, toolText(err)
		}
		out := feedPageJSON{Events: make([]feedItemJSON, len(page.Events)), NextBefore: page.NextBefore}
		for i, it := range page.Events {
			out.Events[i] = feedItemOut(it)
		}
		if page.Facets != nil {
			out.Facets = &facetsJSON{Streams: page.Facets.Streams, SourceTypes: page.Facets.SourceTypes, Capped: page.Facets.Capped}
		}
		return out, nil
	}
	if err := toolText(p.s.svc.RequireStream(ctx, "read", *q.StreamID)); err != nil {
		return nil, err
	}
	after := q.After
	page, err := p.s.svc.ListEvents(ctx, *q.StreamID, &after, nil, q.Limit)
	if err != nil {
		return nil, toolText(err)
	}
	out := eventPageJSON{Events: make([]eventJSON, len(page.Events)), NextAfter: page.NextAfter}
	for i, e := range page.Events {
		out.Events[i] = eventOut(e)
	}
	return out, nil
}

// PlatformStreamEvents is api.PlatformStreamEvents over the streams service.
type PlatformStreamEvents struct{ svc *service.Service }

var _ api.PlatformStreamEvents = PlatformStreamEvents{}

// NewPlatformStreamEvents builds the stream_events toolset's provider.
func NewPlatformStreamEvents(svc *service.Service) PlatformStreamEvents {
	return PlatformStreamEvents{svc: svc}
}

func (p PlatformStreamEvents) Read(ctx context.Context, c authn.Caller, stream string, after int64, limit int, since *time.Time) (api.StreamEventsRead, error) {
	out, err := p.svc.ReadStreamEvents(authn.WithCaller(ctx, c), stream, after, limit, since)
	return out, toolText(err)
}

// PlatformMessages is api.PlatformMessages over the streams service.
type PlatformMessages struct{ svc *service.Service }

var _ api.PlatformMessages = PlatformMessages{}

// NewPlatformMessages builds the messages toolset's provider.
func NewPlatformMessages(svc *service.Service) PlatformMessages { return PlatformMessages{svc: svc} }

func (p PlatformMessages) Send(ctx context.Context, c authn.Caller, in api.MessageSend) (api.MessageSent, error) {
	out, err := p.svc.SendMessage(authn.WithCaller(ctx, c), in)
	return out, toolText(err)
}
