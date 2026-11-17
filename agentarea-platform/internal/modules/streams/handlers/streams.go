package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	openapi_types "github.com/oapi-codegen/runtime/types"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/streams"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

// mountStreams registers streams, subscriptions, forwards, processors and events.
func mountStreams(base chi.Router, w *gen.ServerInterfaceWrapper, _ *Server, _ *httpx.Errors) {
	p := httpx.WorkspacePrefix + "/streams"
	base.Get(p+"/", w.ListStreamsV1StreamsGet)
	base.Post(p+"/", w.CreateStreamV1StreamsPost)
	base.Get(p+"/events", w.ListWorkspaceEventsV1StreamsEventsGet)
	base.Get(p+"/events/live", w.StreamWorkspaceEventsV1StreamsEventsLiveGet)
	base.Get(p+"/events/{event_id}", w.GetEventByIdV1StreamsEventsEventIdGet)
	base.Get(p+"/{stream_id}", w.GetStreamV1StreamsStreamIdGet)
	base.Delete(p+"/{stream_id}", w.DeleteStreamV1StreamsStreamIdDelete)
	base.Get(p+"/{stream_id}/subscriptions", w.ListSubscriptionsV1StreamsStreamIdSubscriptionsGet)
	base.Post(p+"/{stream_id}/forwards", w.CreateForwardV1StreamsStreamIdForwardsPost)
	base.Delete(p+"/{stream_id}/subscriptions/{subscription_id}", w.DeleteForwardV1StreamsStreamIdSubscriptionsSubscriptionIdDelete)
	base.Post(p+"/{stream_id}/processors", w.CreateProcessorV1StreamsStreamIdProcessorsPost)
	base.Patch(p+"/{stream_id}/processors/{subscription_id}", w.UpdateProcessorV1StreamsStreamIdProcessorsSubscriptionIdPatch)
	base.Delete(p+"/{stream_id}/processors/{subscription_id}", w.DeleteProcessorV1StreamsStreamIdProcessorsSubscriptionIdDelete)
	base.Get(p+"/{stream_id}/events", w.ListEventsV1StreamsStreamIdEventsGet)
	base.Get(p+"/{stream_id}/events/{sequence}", w.GetEventV1StreamsStreamIdEventsSequenceGet)
	base.Get(p+"/{stream_id}/subscriptions/{subscription_id}/outcomes", w.ListOutcomesV1StreamsStreamIdSubscriptionsSubscriptionIdOutcomesGet)
}

type streamJSON struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Description string    `json:"description"`
	Kind        string    `json:"kind"`
	CreatedBy   string    `json:"created_by"`
	CreatedAt   time.Time `json:"created_at"`
}

func streamOut(s domain.Stream) streamJSON {
	return streamJSON{ID: s.ID, Name: s.Name, Description: s.Description, Kind: s.Kind, CreatedBy: s.CreatedBy, CreatedAt: s.CreatedAt.UTC()}
}

type subscriptionJSON struct {
	ID              string         `json:"id"`
	Kind            string         `json:"kind"`
	TriggerID       *string        `json:"trigger_id"`
	Filter          map[string]any `json:"filter"`
	OutputStreamIDs []string       `json:"output_stream_ids"`
	Status          string         `json:"status"`
	Code            *string        `json:"code"`
	CreatedAt       time.Time      `json:"created_at"`
}

func subscriptionOut(s domain.Subscription) subscriptionJSON {
	f := s.Filter
	if f == nil {
		f = map[string]any{}
	}
	outs := s.OutputStreamIDs
	if outs == nil {
		outs = []string{}
	}
	return subscriptionJSON{ID: s.ID, Kind: s.Kind, TriggerID: s.TriggerID, Filter: f, OutputStreamIDs: outs,
		Status: s.Status, Code: s.Code, CreatedAt: s.CreatedAt.UTC()}
}

type outcomeJSON struct {
	SubscriptionID   string    `json:"subscription_id"`
	SubscriptionKind string    `json:"subscription_kind"`
	TriggerID        *string   `json:"trigger_id"`
	EventID          string    `json:"event_id"`
	Verdict          string    `json:"verdict"`
	Reason           *string   `json:"reason"`
	Score            *float64  `json:"score"`
	TaskID           *string   `json:"task_id"`
	DerivedEventIDs  []string  `json:"derived_event_ids"`
	CreatedAt        time.Time `json:"created_at"`
}

func strOf(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func outcomeOut(o service.Outcome) outcomeJSON {
	derived := o.DerivedEventIDs
	if derived == nil {
		derived = []string{}
	}
	return outcomeJSON{SubscriptionID: strOf(o.SubscriptionID), SubscriptionKind: o.SubscriptionKind, TriggerID: o.TriggerIDOf,
		EventID: strOf(o.EventID), Verdict: o.ReactionVerdict(), Reason: o.Reason, Score: o.Score, TaskID: o.TaskID,
		DerivedEventIDs: derived, CreatedAt: o.CreatedAt.UTC()}
}

type processingTaskJSON struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

type processingJSON struct {
	Status      string               `json:"status"`
	Subscribers *int                 `json:"subscribers"`
	Reacted     int                  `json:"reacted"`
	Skipped     int                  `json:"skipped"`
	Errors      int                  `json:"errors"`
	Tasks       []processingTaskJSON `json:"tasks"`
}

func processingOut(p service.Processing) processingJSON {
	tasks := make([]processingTaskJSON, len(p.Tasks))
	for i, t := range p.Tasks {
		tasks[i] = processingTaskJSON(t)
	}
	return processingJSON{Status: p.Status, Subscribers: p.Subscribers, Reacted: p.Reacted, Skipped: p.Skipped, Errors: p.Errors, Tasks: tasks}
}

// envelopeJSON is the envelope fields every event response shares, in the order Python writes them.
type envelopeJSON struct {
	Sequence      int64     `json:"sequence"`
	V             int       `json:"v"`
	EventID       string    `json:"event_id"`
	StreamID      string    `json:"stream_id"`
	SourceID      *string   `json:"source_id"`
	SourceType    *string   `json:"source_type"`
	Kind          string    `json:"kind"`
	Key           string    `json:"key"`
	SessionKey    *string   `json:"session_key"`
	Sender        *string   `json:"sender"`
	ReceivedAt    time.Time `json:"received_at"`
	OccurredAt    time.Time `json:"occurred_at"`
	Depth         int       `json:"depth"`
	CorrelationID *string   `json:"correlation_id"`
	CausationID   *string   `json:"causation_id"`
}

func envelopeOut(e domain.RecordedEvent) envelopeJSON {
	return envelopeJSON{Sequence: e.Sequence, V: domain.EnvelopeVersion, EventID: e.ID, StreamID: e.StreamID, SourceID: e.SourceID,
		SourceType: e.SourceType, Kind: e.Kind, Key: e.EventKey, SessionKey: e.SessionKey, Sender: e.Sender,
		ReceivedAt: e.ReceivedAt.UTC(), OccurredAt: e.OccurredAt.UTC(), Depth: e.Depth, CorrelationID: e.CorrelationID,
		CausationID: e.CausationID}
}

type feedItemJSON struct {
	envelopeJSON
	Attachments int            `json:"attachments"`
	Processing  processingJSON `json:"processing"`
}

func feedItemOut(it service.FeedItem) feedItemJSON {
	return feedItemJSON{envelopeJSON: envelopeOut(it.RecordedEvent), Attachments: len(it.Attachments), Processing: processingOut(it.Processing)}
}

type attachmentJSON struct {
	Name   string  `json:"name"`
	Mime   *string `json:"mime"`
	Size   *int64  `json:"size"`
	SHA256 *string `json:"sha256"`
	Ref    string  `json:"ref"`
	URL    *string `json:"url"`
}

type eventJSON struct {
	envelopeJSON
	Data        map[string]any   `json:"data"`
	BodyURL     *string          `json:"body_url"`
	Attachments []attachmentJSON `json:"attachments"`
	Outcomes    []outcomeJSON    `json:"outcomes"`
	Processing  *processingJSON  `json:"processing"`
}

func eventOut(v service.EventView) eventJSON {
	out := eventJSON{envelopeJSON: envelopeOut(v.RecordedEvent), Data: v.Data, BodyURL: v.BodyURL,
		Attachments: make([]attachmentJSON, len(v.Attachments)), Outcomes: make([]outcomeJSON, len(v.Outcomes))}
	if out.Data == nil {
		out.Data = map[string]any{}
	}
	for i, a := range v.Attachments {
		out.Attachments[i] = attachmentJSON{Name: a.Name, Mime: a.Mime, Size: a.Size, SHA256: a.SHA256, Ref: a.Ref}
		if i < len(v.AttachmentURLs) {
			out.Attachments[i].URL = v.AttachmentURLs[i]
		}
	}
	for i, o := range v.Outcomes {
		out.Outcomes[i] = outcomeOut(o)
	}
	if v.Processing != nil {
		p := processingOut(*v.Processing)
		out.Processing = &p
	}
	return out
}

type handlerJSON struct {
	SubscriptionID  string   `json:"subscription_id"`
	Kind            string   `json:"kind"`
	Name            string   `json:"name"`
	Verdict         string   `json:"verdict"`
	Reason          *string  `json:"reason"`
	TaskID          *string  `json:"task_id"`
	TaskStatus      *string  `json:"task_status"`
	DerivedEventIDs []string `json:"derived_event_ids"`
}

type eventDetailJSON struct {
	eventJSON
	Handlers []handlerJSON `json:"handlers"`
}

func eventDetailOut(d service.EventDetail) eventDetailJSON {
	out := eventDetailJSON{eventJSON: eventOut(d.EventView), Handlers: make([]handlerJSON, len(d.Handlers))}
	for i, h := range d.Handlers {
		derived := h.DerivedEventIDs
		if derived == nil {
			derived = []string{}
		}
		out.Handlers[i] = handlerJSON{SubscriptionID: h.SubscriptionID, Kind: h.Kind, Name: h.Name, Verdict: h.Verdict,
			Reason: h.Reason, TaskID: h.TaskID, TaskStatus: h.TaskStatus, DerivedEventIDs: derived}
	}
	return out
}

func boundInt(v *int, def, ge int, le int64, name string) (int, error) {
	if v == nil {
		return def, nil
	}
	if *v < ge {
		return 0, httpx.Validation(httpx.GreaterThanEqual(ge, "query", name))
	}
	if int64(*v) > le {
		return 0, httpx.Validation(httpx.LessThanEqual(le, "query", name))
	}
	return *v, nil
}

func optBound(v *int, ge int, name string) (*int64, error) {
	if v == nil {
		return nil, nil
	}
	n, err := boundInt(v, 0, ge, httpx.MaxBigint, name)
	if err != nil {
		return nil, err
	}
	out := int64(n)
	return &out, nil
}

func (s *Server) ListStreamsV1StreamsGet(ctx context.Context, req gen.ListStreamsV1StreamsGetRequestObject) (gen.ListStreamsV1StreamsGetResponseObject, error) {
	limit, err := boundInt(req.Params.Limit, 100, 1, 1000, "limit")
	if err != nil {
		return nil, err
	}
	offset, err := boundInt(req.Params.Offset, 0, 0, httpx.MaxOffset, "offset")
	if err != nil {
		return nil, err
	}
	rows, err := s.svc.ListStreams(ctx, limit, offset)
	if err != nil {
		return nil, err
	}
	out := make([]streamJSON, len(rows))
	for i, r := range rows {
		out[i] = streamOut(r)
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) CreateStreamV1StreamsPost(ctx context.Context, req gen.CreateStreamV1StreamsPostRequestObject) (gen.CreateStreamV1StreamsPostResponseObject, error) {
	if req.Body == nil {
		return nil, httpx.Validation(httpx.Missing("body"))
	}
	desc := ""
	if req.Body.Description != nil {
		desc = *req.Body.Description
	}
	var errs []httpx.FieldError
	if n := len([]rune(req.Body.Name)); n < 1 {
		errs = append(errs, httpx.StringTooShort(1, "body", "name"))
	} else if n > 255 {
		errs = append(errs, httpx.StringTooLong(255, "body", "name"))
	}
	if len([]rune(desc)) > 1000 {
		errs = append(errs, httpx.StringTooLong(1000, "body", "description"))
	}
	if err := httpx.Validation(errs...); err != nil {
		return nil, err
	}
	st, err := s.svc.CreateStream(ctx, req.Body.Name, desc)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: streamOut(st)}, nil
}

func (s *Server) GetStreamV1StreamsStreamIdGet(ctx context.Context, req gen.GetStreamV1StreamsStreamIdGetRequestObject) (gen.GetStreamV1StreamsStreamIdGetResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "read", id); err != nil {
		return nil, err
	}
	st, err := s.svc.GetStream(ctx, id)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: streamOut(st)}, nil
}

func (s *Server) DeleteStreamV1StreamsStreamIdDelete(ctx context.Context, req gen.DeleteStreamV1StreamsStreamIdDeleteRequestObject) (gen.DeleteStreamV1StreamsStreamIdDeleteResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "delete", id); err != nil {
		return nil, err
	}
	if err := s.svc.DeleteStream(ctx, id); err != nil {
		return nil, err
	}
	return response{status: http.StatusNoContent}, nil
}

func (s *Server) ListSubscriptionsV1StreamsStreamIdSubscriptionsGet(ctx context.Context, req gen.ListSubscriptionsV1StreamsStreamIdSubscriptionsGetRequestObject) (gen.ListSubscriptionsV1StreamsStreamIdSubscriptionsGetResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "read", id); err != nil {
		return nil, err
	}
	rows, err := s.svc.ListSubscriptions(ctx, id)
	if err != nil {
		return nil, err
	}
	out := make([]subscriptionJSON, len(rows))
	for i, r := range rows {
		out[i] = subscriptionOut(r)
	}
	return response{status: http.StatusOK, body: out}, nil
}

func uuidStrings(ids []openapi_types.UUID) []string {
	out := make([]string, len(ids))
	for i, id := range ids {
		out[i] = id.String()
	}
	return out
}

func eventFilter(f *gen.EventFilter) domain.EventFilter {
	out := domain.EventFilter{Kinds: []string{}, Fields: map[string]any{}}
	if f == nil {
		return out
	}
	if f.Kinds != nil {
		out.Kinds = *f.Kinds
	}
	if f.Fields != nil {
		out.Fields = *f.Fields
	}
	return out
}

func (s *Server) CreateForwardV1StreamsStreamIdForwardsPost(ctx context.Context, req gen.CreateForwardV1StreamsStreamIdForwardsPostRequestObject) (gen.CreateForwardV1StreamsStreamIdForwardsPostResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "edit", id); err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, httpx.Validation(httpx.Missing("body"))
	}
	if len(req.Body.OutputStreamIds) == 0 {
		return nil, httpx.Validation(listTooShort("output_stream_ids"))
	}
	sub, err := s.svc.CreateForward(ctx, id, uuidStrings(req.Body.OutputStreamIds), eventFilter(req.Body.EventFilter))
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: subscriptionOut(sub)}, nil
}

func listTooShort(field string) httpx.FieldError {
	return httpx.FieldError{Type: "too_short", Loc: []any{"body", field},
		Msg: "List should have at least 1 item after validation, not 0"}
}

func (s *Server) DeleteForwardV1StreamsStreamIdSubscriptionsSubscriptionIdDelete(ctx context.Context, req gen.DeleteForwardV1StreamsStreamIdSubscriptionsSubscriptionIdDeleteRequestObject) (gen.DeleteForwardV1StreamsStreamIdSubscriptionsSubscriptionIdDeleteResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "edit", id); err != nil {
		return nil, err
	}
	if err := s.svc.DeleteForward(ctx, id, req.SubscriptionId.String()); err != nil {
		return nil, err
	}
	return response{status: http.StatusNoContent}, nil
}

func (s *Server) CreateProcessorV1StreamsStreamIdProcessorsPost(ctx context.Context, req gen.CreateProcessorV1StreamsStreamIdProcessorsPostRequestObject) (gen.CreateProcessorV1StreamsStreamIdProcessorsPostResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "edit", id); err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, httpx.Validation(httpx.Missing("body"))
	}
	var errs []httpx.FieldError
	if len(req.Body.OutputStreamIds) == 0 {
		errs = append(errs, listTooShort("output_stream_ids"))
	}
	if req.Body.Code == "" {
		errs = append(errs, httpx.StringTooShort(1, "body", "code"))
	}
	if err := httpx.Validation(errs...); err != nil {
		return nil, err
	}
	sub, err := s.svc.CreateProcessor(ctx, id, uuidStrings(req.Body.OutputStreamIds), req.Body.Code, eventFilter(req.Body.EventFilter))
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: subscriptionOut(sub)}, nil
}

func (s *Server) UpdateProcessorV1StreamsStreamIdProcessorsSubscriptionIdPatch(ctx context.Context, req gen.UpdateProcessorV1StreamsStreamIdProcessorsSubscriptionIdPatchRequestObject) (gen.UpdateProcessorV1StreamsStreamIdProcessorsSubscriptionIdPatchResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "edit", id); err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, httpx.Validation(httpx.Missing("body"))
	}
	p := service.ProcessorPatch{Code: req.Body.Code}
	var errs []httpx.FieldError
	if req.Body.OutputStreamIds != nil {
		if len(*req.Body.OutputStreamIds) == 0 {
			errs = append(errs, listTooShort("output_stream_ids"))
		}
		p.Outputs = uuidStrings(*req.Body.OutputStreamIds)
	}
	if p.Code != nil && *p.Code == "" {
		errs = append(errs, httpx.StringTooShort(1, "body", "code"))
	}
	if err := httpx.Validation(errs...); err != nil {
		return nil, err
	}
	if req.Body.EventFilter != nil {
		f := eventFilter(req.Body.EventFilter)
		p.Filter = &f
	}
	sub, err := s.svc.UpdateProcessor(ctx, id, req.SubscriptionId.String(), p)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: subscriptionOut(sub)}, nil
}

func (s *Server) DeleteProcessorV1StreamsStreamIdProcessorsSubscriptionIdDelete(ctx context.Context, req gen.DeleteProcessorV1StreamsStreamIdProcessorsSubscriptionIdDeleteRequestObject) (gen.DeleteProcessorV1StreamsStreamIdProcessorsSubscriptionIdDeleteResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "edit", id); err != nil {
		return nil, err
	}
	if err := s.svc.DeleteProcessor(ctx, id, req.SubscriptionId.String()); err != nil {
		return nil, err
	}
	return response{status: http.StatusNoContent}, nil
}

func (s *Server) ListOutcomesV1StreamsStreamIdSubscriptionsSubscriptionIdOutcomesGet(ctx context.Context, req gen.ListOutcomesV1StreamsStreamIdSubscriptionsSubscriptionIdOutcomesGetRequestObject) (gen.ListOutcomesV1StreamsStreamIdSubscriptionsSubscriptionIdOutcomesGetResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "read", id); err != nil {
		return nil, err
	}
	limit, err := boundInt(req.Params.Limit, 50, 1, service.OutcomesMax, "limit")
	if err != nil {
		return nil, err
	}
	rows, err := s.svc.ListOutcomes(ctx, id, req.SubscriptionId.String(), limit)
	if err != nil {
		return nil, err
	}
	out := make([]outcomeJSON, len(rows))
	for i, r := range rows {
		out[i] = outcomeOut(r)
	}
	return response{status: http.StatusOK, body: out}, nil
}

type eventPageJSON struct {
	Events     []eventJSON `json:"events"`
	NextAfter  *int64      `json:"next_after"`
	NextBefore *int64      `json:"next_before"`
}

func (s *Server) ListEventsV1StreamsStreamIdEventsGet(ctx context.Context, req gen.ListEventsV1StreamsStreamIdEventsGetRequestObject) (gen.ListEventsV1StreamsStreamIdEventsGetResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "read", id); err != nil {
		return nil, err
	}
	after, err := optBound(req.Params.After, 0, "after")
	if err != nil {
		return nil, err
	}
	before, err := optBound(req.Params.Before, 1, "before")
	if err != nil {
		return nil, err
	}
	limit, err := boundInt(req.Params.Limit, 50, 1, 200, "limit")
	if err != nil {
		return nil, err
	}
	page, err := s.svc.ListEvents(ctx, id, after, before, limit)
	if err != nil {
		return nil, err
	}
	out := eventPageJSON{Events: make([]eventJSON, len(page.Events)), NextAfter: page.NextAfter, NextBefore: page.NextBefore}
	for i, e := range page.Events {
		out.Events[i] = eventOut(e)
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) GetEventV1StreamsStreamIdEventsSequenceGet(ctx context.Context, req gen.GetEventV1StreamsStreamIdEventsSequenceGetRequestObject) (gen.GetEventV1StreamsStreamIdEventsSequenceGetResponseObject, error) {
	id := req.StreamId.String()
	if err := s.svc.RequireStream(ctx, "read", id); err != nil {
		return nil, err
	}
	if req.Sequence < 1 {
		return nil, httpx.Validation(httpx.GreaterThanEqual(1, "path", "sequence"))
	}
	d, err := s.svc.GetEvent(ctx, id, int64(req.Sequence))
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: eventDetailOut(d)}, nil
}

func (s *Server) GetEventByIdV1StreamsEventsEventIdGet(ctx context.Context, req gen.GetEventByIdV1StreamsEventsEventIdGetRequestObject) (gen.GetEventByIdV1StreamsEventsEventIdGetResponseObject, error) {
	d, err := s.svc.GetEventByID(ctx, req.EventId.String())
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: eventDetailOut(d)}, nil
}

// feedFilter is feed_filter: the feed's query, its strings bounded as the route bounds them.
func feedFilter(streamID *openapi_types.UUID, sourceType, kind, sender, sessionKey *string, result *gen.ProcessingStatus,
	since, until *time.Time, platform *bool) (domain.FeedFilter, error) {
	f := domain.FeedFilter{SourceType: sourceType, Kind: kind, Sender: sender, SessionKey: sessionKey, Since: since, Until: until, Platform: true}
	if streamID != nil {
		id := streamID.String()
		f.StreamID = &id
	}
	var errs []httpx.FieldError
	for _, c := range []struct {
		v    *string
		max  int
		name string
	}{{sourceType, 64, "source_type"}, {kind, 255, "kind"}, {sender, 512, "sender"}, {sessionKey, 512, "session_key"}} {
		if c.v != nil && len([]rune(*c.v)) > c.max {
			errs = append(errs, httpx.StringTooLong(c.max, "query", c.name))
		}
	}
	if result != nil {
		r := string(*result)
		valid := domain.ProcessingStatuses()
		ok := false
		for _, v := range valid {
			ok = ok || v == r
		}
		if !ok {
			errs = append(errs, httpx.EnumError(valid, "query", "result"))
		}
		f.Result = &r
	}
	if platform != nil {
		f.Platform = *platform
	}
	return f, httpx.Validation(errs...)
}

type facetsJSON struct {
	Streams     map[string]int64 `json:"streams"`
	SourceTypes map[string]int64 `json:"source_types"`
	Capped      bool             `json:"capped"`
}

type feedPageJSON struct {
	Events     []feedItemJSON `json:"events"`
	NextBefore *int64         `json:"next_before"`
	Facets     *facetsJSON    `json:"facets"`
}

func (s *Server) ListWorkspaceEventsV1StreamsEventsGet(ctx context.Context, req gen.ListWorkspaceEventsV1StreamsEventsGetRequestObject) (gen.ListWorkspaceEventsV1StreamsEventsGetResponseObject, error) {
	p := req.Params
	f, err := feedFilter(p.StreamId, p.SourceType, p.Kind, p.Sender, p.SessionKey, p.Result, p.Since, p.Until, p.Platform)
	if err != nil {
		return nil, err
	}
	before, err := optBound(p.Before, 1, "before")
	if err != nil {
		return nil, err
	}
	limit, err := boundInt(p.Limit, 50, 1, 200, "limit")
	if err != nil {
		return nil, err
	}
	page, err := s.svc.WorkspaceFeed(ctx, f, before, limit)
	if err != nil {
		return nil, err
	}
	out := feedPageJSON{Events: make([]feedItemJSON, len(page.Events)), NextBefore: page.NextBefore}
	for i, it := range page.Events {
		out.Events[i] = feedItemOut(it)
	}
	if page.Facets != nil {
		out.Facets = &facetsJSON{Streams: page.Facets.Streams, SourceTypes: page.Facets.SourceTypes, Capped: page.Facets.Capped}
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) StreamWorkspaceEventsV1StreamsEventsLiveGet(ctx context.Context, req gen.StreamWorkspaceEventsV1StreamsEventsLiveGetRequestObject) (gen.StreamWorkspaceEventsV1StreamsEventsLiveGetResponseObject, error) {
	p := req.Params
	f, err := feedFilter(p.StreamId, p.SourceType, p.Kind, p.Sender, p.SessionKey, p.Result, p.Since, p.Until, p.Platform)
	if err != nil {
		return nil, err
	}
	frames, err := s.svc.LiveFeed(ctx, f)
	if errors.Is(err, service.ErrLiveUnavailable) {
		return nil, httpx.HTTPError(http.StatusServiceUnavailable, "The live events feed is not available")
	}
	if err != nil {
		return nil, err
	}
	return liveResponse{ctx: ctx, frames: frames, log: s.log}, nil
}

type liveResponse struct {
	ctx    context.Context
	frames <-chan service.LiveFrame
	log    interface{ Error(string, ...any) }
}

type processingNoticeJSON struct {
	EventID    string         `json:"event_id"`
	Processing processingJSON `json:"processing"`
}

func liveFrame(f service.LiveFrame) ([]byte, error) {
	var data any = feedItemOut(f.Item)
	if f.Kind == service.NoticeProcessing {
		data = processingNoticeJSON{EventID: f.Item.ID, Processing: processingOut(f.Item.Processing)}
	}
	raw, err := json.Marshal(data)
	if err != nil {
		return nil, err
	}
	return []byte("event: " + f.Kind + "\ndata: " + string(raw) + "\n\n"), nil
}

func (x liveResponse) VisitStreamWorkspaceEventsV1StreamsEventsLiveGetResponse(w http.ResponseWriter) error {
	h := w.Header()
	h.Set("Content-Type", "text/event-stream; charset=utf-8")
	h.Set("Cache-Control", "no-cache")
	h.Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)
	rc := http.NewResponseController(w)
	write := func(b []byte) error {
		if _, err := w.Write(b); err != nil {
			return err
		}
		if err := rc.Flush(); err != nil && !errors.Is(err, http.ErrNotSupported) {
			return err
		}
		return nil
	}
	if err := write(httpx.SSEComment("subscribed")); err != nil {
		return err
	}
	ticker := time.NewTicker(httpx.SSEHeartbeat)
	defer ticker.Stop()
	for {
		select {
		case <-x.ctx.Done():
			return nil
		case <-ticker.C:
			if err := write([]byte(httpx.SSEPing)); err != nil {
				return nil
			}
		case f, ok := <-x.frames:
			if !ok {
				return nil
			}
			frame, err := liveFrame(f)
			if err != nil {
				x.log.Error("Failed to encode a live events frame", "error", err.Error())
				return nil
			}
			if err := write(frame); err != nil {
				return nil
			}
			ticker.Reset(httpx.SSEHeartbeat)
		}
	}
}

func (x response) VisitListStreamsV1StreamsGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitCreateStreamV1StreamsPostResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitListWorkspaceEventsV1StreamsEventsGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitGetEventByIdV1StreamsEventsEventIdGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitDeleteStreamV1StreamsStreamIdDeleteResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitGetStreamV1StreamsStreamIdGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitListEventsV1StreamsStreamIdEventsGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitGetEventV1StreamsStreamIdEventsSequenceGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitCreateForwardV1StreamsStreamIdForwardsPostResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitCreateProcessorV1StreamsStreamIdProcessorsPostResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitDeleteProcessorV1StreamsStreamIdProcessorsSubscriptionIdDeleteResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitUpdateProcessorV1StreamsStreamIdProcessorsSubscriptionIdPatchResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitListSubscriptionsV1StreamsStreamIdSubscriptionsGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitDeleteForwardV1StreamsStreamIdSubscriptionsSubscriptionIdDeleteResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitListOutcomesV1StreamsStreamIdSubscriptionsSubscriptionIdOutcomesGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
