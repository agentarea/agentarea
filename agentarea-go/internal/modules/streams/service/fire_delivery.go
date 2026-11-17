package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"

	"github.com/google/uuid"

	kblob "github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

const defaultIdleTimeout = "30m"

// EventBody is delivery_address.event_body: the body as sent, inline or read back from the
// workspace file a large one moved to.
func (s *Service) EventBody(ctx context.Context, e domain.Event) (any, error) {
	ref, _ := e.Data["body_ref"].(string)
	if e.Data["body"] != nil || ref == "" {
		return e.Data["body"], nil
	}
	if s.d.Blob == nil {
		return nil, fmt.Errorf("streams: event body %q needs the artifacts bucket, which is not wired", ref)
	}
	scoped, err := kblob.ForWorkspace(s.d.Blob, e.WorkspaceID)
	if err != nil {
		return nil, err
	}
	rc, _, err := scoped.Get(ctx, ref)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rc.Close() }()
	raw, err := io.ReadAll(rc)
	if err != nil {
		return nil, err
	}
	var body any
	d := json.NewDecoder(bytesReader(raw))
	d.UseNumber()
	if err := d.Decode(&body); err != nil {
		return nil, fmt.Errorf("event body %s: %w", ref, err)
	}
	return body, nil
}

// ErrAdmissionLookup is event_admission's LookupError: a door that cannot be checked stays shut.
var ErrAdmissionLookup = errors.New("sender admission lookup")

// EventAdmission is event_admission: what admits the sender of e; nil when its source type admits
// anyone. An ErrAdmissionLookup error when the source or type cannot be read, or a type with an
// admission names no source: a door that cannot be checked stays shut.
func (s *Service) EventAdmission(ctx context.Context, ws scope.Workspace, e domain.Event) (*Door, error) {
	if e.SourceID == nil {
		if e.SourceType == nil {
			return nil, nil
		}
		entry, ok, err := s.SourceTypeEntry(ctx, *e.SourceType)
		if err != nil {
			return nil, err
		}
		if !ok {
			return nil, fmt.Errorf("%w: source type %q of event %s is not in the catalog", ErrAdmissionLookup, *e.SourceType, e.ID)
		}
		if entry.Admission == nil {
			return nil, nil
		}
		return nil, fmt.Errorf("%w: event %s of source type %q names no source to admit its sender through",
			ErrAdmissionLookup, e.ID, *e.SourceType)
	}
	src, ok, err := s.sourceOf(ctx, ws, e)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, fmt.Errorf("%w: source %s of event %s is gone", ErrAdmissionLookup, *e.SourceID, e.ID)
	}
	slug := ""
	if src.SourceType != nil {
		slug = *src.SourceType
	}
	entry, ok, err := s.SourceTypeEntry(ctx, slug)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, fmt.Errorf("%w: source type %q of event %s is not in the catalog", ErrAdmissionLookup, slug, e.ID)
	}
	if entry.Admission == nil {
		return nil, nil
	}
	if src.CredentialKey == nil {
		return nil, fmt.Errorf("%w: source %s has no credentials", ErrAdmissionLookup, src.ID)
	}
	door := &Door{Admission: *entry.Admission, Source: src, Slug: slug, Senders: domain.Senders{Allow: domain.SendersMembers}}
	if len(src.Senders) > 0 {
		chosen, ok := domain.SendersRecordOf(src.Senders)
		if !ok {
			return nil, fmt.Errorf("%w: source %s stores a senders choice that cannot be read", ErrAdmissionLookup, src.ID)
		}
		door.Senders, door.OwnerID = chosen, *chosen.By
	}
	return door, nil
}

func (s *Service) sourceOf(ctx context.Context, ws scope.Workspace, e domain.Event) (domain.Source, bool, error) {
	var src domain.Source
	var ok bool
	streamID, err := uuid.Parse(e.StreamID)
	if err != nil {
		return src, false, err
	}
	id, err := uuid.Parse(*e.SourceID)
	if err != nil {
		return src, false, nil
	}
	err = s.read(ctx, ws, func(sess db.Session) error {
		src, ok, err = s.ss.GetSource(ctx, sess, streamID, id)
		return err
	})
	return src, ok && src.WorkspaceID == e.WorkspaceID, err
}

// FiringDelivery is delivery_address.firing_delivery: the reply address and session of the task
// a stream event starts, read from the source that brought it and its catalog entry. A copy
// (depth > 0) or an event with no source has neither.
func (s *Service) FiringDelivery(ctx context.Context, ws scope.Workspace, e domain.Event, triggerID string, setting *domain.Session, body any) (TaskDelivery, error) {
	eventID := e.ID
	base := TaskDelivery{StreamEventID: &eventID}
	if e.SourceID == nil || e.Depth > 0 {
		return base, nil
	}
	src, ok, err := s.sourceOf(ctx, ws, e)
	if err != nil {
		return base, err
	}
	if !ok {
		s.log.WarnContext(ctx, "Event names a source not in its workspace; its task does not reply", "event_id", e.ID, "source_id", *e.SourceID)
		return base, nil
	}
	if src.SourceType == nil || *src.SourceType == "" {
		s.log.ErrorContext(ctx, "Source has no type; its task does not reply", "source_id", src.ID)
		return TaskDelivery{StreamEventID: &eventID}, nil
	}
	slug := *src.SourceType
	entry, found, err := s.SourceTypeEntry(ctx, slug)
	if err != nil {
		return base, err
	}
	if !found {
		s.log.ErrorContext(ctx, "Source is of a type the catalog has no entry for; its task does not reply", "source_id", src.ID, "slug", slug)
		return TaskDelivery{SourceType: &slug, StreamEventID: &eventID}, nil
	}
	headers := map[string]string{}
	if h, ok := e.Data["headers"].(map[string]any); ok {
		for k, v := range h {
			if sv, ok := v.(string); ok {
				headers[k] = sv
			}
		}
	}
	session, err := taskSession(setting, &entry, e.SessionKey)
	if err != nil {
		return base, err
	}
	return TaskDelivery{SourceType: &slug, StreamEventID: &eventID, Session: session,
		Address: s.deliveryAddress(ctx, entry, src, triggerID, e.SessionKey, body, headers)}, nil
}

// deliveryAddress is build_delivery_address; nil when the entry has no reply or the event no target.
func (s *Service) deliveryAddress(ctx context.Context, entry domain.SourceTypeEntry, src domain.Source, triggerID string, sessionKey *string, body any, headers map[string]string) map[string]any {
	reply := entry.Reply
	if reply == nil {
		return nil
	}
	tpl := make(map[string]any, len(reply.Target))
	for k, v := range reply.Target {
		tpl[k] = v
	}
	target := domain.RenderValue(tpl, domain.TemplateContext{Body: body, Headers: headers})
	if len(reply.Target) > 0 && empty(target) {
		s.log.WarnContext(ctx, "An event of a source has nothing to reply to; its task does not reply", "source_id", src.ID, "slug", entry.Slug)
		return nil
	}
	var credKey, sk any
	if src.CredentialKey != nil {
		credKey = *src.CredentialKey
	}
	if sessionKey != nil {
		sk = *sessionKey
	}
	return map[string]any{
		"type": entry.Slug, "sender": reply.Sender, "source_id": src.ID, "credential_type": entry.Slug,
		"credential_key": credKey, "trigger_id": triggerID, "session_key": sk, "target": target,
		"presentation": reply.Presentation,
	}
}

func empty(v any) bool {
	switch x := v.(type) {
	case nil:
		return true
	case map[string]any:
		return len(x) == 0
	case string:
		return x == ""
	}
	return false
}

// taskSession is delivery_address.task_session; nil for an event with no session key.
func taskSession(setting *domain.Session, entry *domain.SourceTypeEntry, sessionKey *string) (map[string]any, error) {
	if sessionKey == nil {
		return nil, nil
	}
	var continues *bool
	if setting != nil {
		continues = setting.Continue
	}
	if continues == nil {
		c := entry != nil && entry.ContinuesSessions()
		continues = &c
	}
	idle := defaultIdleTimeout
	if setting != nil && setting.IdleTimeout != nil && *setting.IdleTimeout != "" {
		idle = *setting.IdleTimeout
	}
	d, err := config.ParseDuration(idle)
	if err != nil {
		return nil, err
	}
	return map[string]any{"key": *sessionKey, "continue": *continues, "idle_timeout_seconds": int(d.Seconds())}, nil
}

func bytesReader(b []byte) io.Reader { return bytes.NewReader(b) }
