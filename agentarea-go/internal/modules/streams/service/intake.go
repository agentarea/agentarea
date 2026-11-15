package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"mime"
	"path"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	kblob "github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// EventFilesPrefix is where an event's offloaded body and files live in its workspace's files.
const EventFilesPrefix = "events"

// dedupHold is how long a claimed event id is held before it is kept or released.
const dedupHold = 5 * time.Minute

var (
	// ErrCredentialsUnavailable is a source's credentials that exist but cannot be used.
	ErrCredentialsUnavailable = errors.New("source credentials unavailable")
	// ErrSecretStoreUnreachable is the secret store not answering; it is also ErrCredentialsUnavailable.
	ErrSecretStoreUnreachable = errors.New("secret store unreachable")
	// ErrMalformedItem is a polled item no retry can ingest (dead-lettered).
	ErrMalformedItem = errors.New("malformed polled item")
)

type credentialsError struct {
	unreachable bool
	msg         string
	cause       error
}

func (e *credentialsError) Error() string { return e.msg }
func (e *credentialsError) Unwrap() error { return e.cause }
func (e *credentialsError) Is(target error) bool {
	return target == ErrCredentialsUnavailable || (e.unreachable && target == ErrSecretStoreUnreachable)
}

// BusEvent is StreamEvent.to_bus: the stream attributes as CloudEvents extensions.
func BusEvent(e domain.Event) events.IntegrationEvent {
	x := map[string]string{
		"streamid": e.StreamID, "workspaceid": e.WorkspaceID, "createdby": e.CreatedBy, "eventkey": e.EventKey,
		"receivedat": events.PyISO(e.ReceivedAt), "depth": strconv.Itoa(e.Depth),
	}
	for k, v := range map[string]*string{"sourceid": e.SourceID, "sourcetype": e.SourceType, "sessionkey": e.SessionKey, "sender": e.Sender} {
		if v != nil {
			x[k] = *v
		}
	}
	if len(e.Attachments) > 0 {
		b, err := compactJSON(e.Attachments)
		if err == nil {
			x["attachments"] = string(b)
		}
	}
	out := events.IntegrationEvent{ID: e.ID, Type: e.Kind, Source: e.Source, Time: e.OccurredAt, Data: e.Data, Extensions: x}
	if e.Subject != nil {
		out.Subject = *e.Subject
	}
	if e.CorrelationID != nil {
		out.CorrelationID = *e.CorrelationID
	}
	if e.CausationID != nil {
		out.CausationID = *e.CausationID
	}
	return out
}

// Append is StreamIngest.append: the stream must be in sess's workspace, the workspace quota is
// taken, and the event is published once to its stream's partition; false for a repeat.
func (s *Service) Append(ctx context.Context, sess db.Session, e domain.Event) (bool, error) {
	if strings.TrimSpace(e.EventKey) == "" {
		return false, domain.Invalid("event_key is required: name what distinguishes this event")
	}
	stream, err := uuid.Parse(e.StreamID)
	if err != nil {
		return false, domain.StreamNotFound(e.StreamID)
	}
	if _, ok, err := s.ss.GetStream(ctx, sess, stream); err != nil {
		return false, err
	} else if !ok {
		return false, domain.StreamNotFound(e.StreamID)
	}
	if e.ReceivedAt.IsZero() {
		e.ReceivedAt = s.now()
	}
	if e.WorkspaceID == "" {
		e.WorkspaceID = sess.Workspace().ID()
	}
	limit := s.d.Settings.WriteQuota
	if s.d.Quota != nil {
		ok, err := s.d.Quota.Admit(ctx, e.WorkspaceID, limit)
		if err != nil {
			return false, err
		}
		if !ok {
			return false, domain.Fail(domain.ErrQuotaExceeded, fmt.Sprintf("Workspace %s exceeded %d events per minute", e.WorkspaceID, limit))
		}
	}
	if e.ID == "" {
		e.ID = domain.EventIDFor(stream.String(), e.EventKey)
	}
	if e.CorrelationID == nil {
		id := e.ID
		e.CorrelationID = &id
	}
	if e.Data == nil {
		e.Data = map[string]any{}
	}
	if e.Attachments == nil {
		e.Attachments = []domain.Attachment{}
	}
	claimed, err := s.d.Dedup.Claim(ctx, e.ID, dedupHold)
	if err != nil {
		return false, err
	}
	if !claimed {
		return false, nil
	}
	if err := s.d.Bus.Publish(ctx, BusEvent(e), events.StreamEventsPartition(stream, s.partitions())); err != nil {
		if rerr := s.d.Dedup.Release(context.WithoutCancel(ctx), e.ID); rerr != nil {
			s.log.ErrorContext(ctx, "Releasing the dedup claim of an unpublished event failed", "event_id", e.ID, "error", rerr.Error())
		}
		return false, err
	}
	if err := s.d.Dedup.Keep(ctx, e.ID); err != nil {
		s.log.WarnContext(ctx, "Keeping the dedup claim of a published event failed", "event_id", e.ID, "error", err.Error())
	}
	return true, nil
}

func (s *Service) partitions() int {
	if s.d.Settings.Partitions > 0 {
		return s.d.Settings.Partitions
	}
	return DefaultSettings().Partitions
}

// Receipt is an event a source brought: its id, and false when it repeated one already appended.
type Receipt struct {
	EventID  string
	Appended bool
}

type intake struct {
	src          domain.Source
	entry        domain.SourceTypeEntry
	body         any
	headers      map[string]string
	receivedAt   time.Time
	kindOverride string
	keyOverride  string
}

func eventFilePath(streamID, eventID, name string) string {
	return EventFilesPrefix + "/" + streamID + "/" + eventID + "/" + name
}

var unsafeNameRE = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func safeName(name string) string {
	cleaned := strings.Trim(unsafeNameRE.ReplaceAllString(name, "_"), "._")
	if len(cleaned) > 120 {
		cleaned = cleaned[:120]
	}
	if cleaned == "" {
		return "file"
	}
	return cleaned
}

func textOf(item map[string]any, keys ...string) *string {
	for _, k := range keys {
		if v, ok := item[k].(string); ok && v != "" {
			return &v
		}
	}
	return nil
}

func intOf(item map[string]any, keys ...string) *int64 {
	for _, k := range keys {
		switch v := item[k].(type) {
		case json.Number:
			if n, err := v.Int64(); err == nil {
				return &n
			}
		case float64:
			if v == float64(int64(v)) {
				n := int64(v)
				return &n
			}
		case int:
			n := int64(v)
			return &n
		}
	}
	return nil
}

func compactJSON(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

func (s *Service) putFile(ctx context.Context, workspaceID, p string, data []byte, contentType string) error {
	if s.d.Blob == nil {
		return errors.New("event files need the artifacts bucket")
	}
	scoped, err := kblob.ForWorkspace(s.d.Blob, workspaceID)
	if err != nil {
		return err
	}
	if contentType == "" {
		contentType = mime.TypeByExtension(path.Ext(p))
	}
	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	return scoped.Put(ctx, p, bytes.NewReader(data), int64(len(data)), kblob.PutOptions{
		ContentType: contentType, Metadata: map[string]string{"sha256": digest}, SHA256: digest,
	})
}

// storeAttachments is the body without inline file bytes, and the event's attachments.
func (s *Service) storeAttachments(ctx context.Context, in intake, eventID string) (any, []domain.Attachment, error) {
	p, ok := domain.AttachmentPath(in.entry, in.body)
	if !ok {
		return in.body, []domain.Attachment{}, nil
	}
	fetch := in.entry.Event.Attachments.Fetch
	if fetch != "inline" {
		var out []domain.Attachment
		for _, item := range domain.AttachmentItems(in.body, p) {
			name := "file"
			if n := textOf(item, "file_name", "name", "filename", "title"); n != nil {
				name = *n
			}
			ref, err := compactJSON(map[string]any{"fetch": fetch, "item": item})
			if err != nil {
				return nil, nil, err
			}
			out = append(out, domain.Attachment{
				Name: name, Mime: textOf(item, "mime_type", "mimetype", "mime", "content_type"),
				Size: intOf(item, "file_size", "size"), Ref: string(ref), Stored: false,
			})
		}
		if out == nil {
			out = []domain.Attachment{}
		}
		return in.body, out, nil
	}
	body := deepCopy(in.body)
	out := []domain.Attachment{}
	for i, item := range domain.AttachmentItems(body, p) {
		encoded, isText := item["content_base64"].(string)
		delete(item, "content_base64")
		if !isText {
			continue
		}
		data, err := base64.StdEncoding.Strict().DecodeString(encoded)
		if err != nil {
			s.log.WarnContext(ctx, "Attachment of an event is not base64; left out", "index", i, "event_id", eventID)
			continue
		}
		name := fmt.Sprintf("attachment-%d", i)
		if n := textOf(item, "name", "filename", "file_name"); n != nil {
			name = *n
		}
		mt := textOf(item, "mime", "mime_type", "content_type")
		ref := eventFilePath(in.src.StreamID, eventID, fmt.Sprintf("%d-%s", i, safeName(name)))
		ct := ""
		if mt != nil {
			ct = *mt
		}
		if err := s.putFile(ctx, in.src.WorkspaceID, ref, data, ct); err != nil {
			return nil, nil, err
		}
		item["ref"] = ref
		sum := sha256.Sum256(data)
		digest := hex.EncodeToString(sum[:])
		size := int64(len(data))
		out = append(out, domain.Attachment{Name: name, Mime: mt, Size: &size, SHA256: &digest, Ref: ref, Stored: true})
	}
	return body, out, nil
}

func deepCopy(v any) any {
	switch x := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(x))
		for k, item := range x {
			out[k] = deepCopy(item)
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, item := range x {
			out[i] = deepCopy(item)
		}
		return out
	}
	return v
}

// ingest is SourceIntake.ingest: the envelope by the entry's templates, files to the workspace's
// files, and the event appended to the source's stream; a repeat of its key is the same event.
func (s *Service) ingest(ctx context.Context, sess db.Session, in intake) (Receipt, error) {
	overrides, err := domain.ParseEventOverrides(in.src.EventTemplates)
	if err != nil {
		return Receipt{}, err
	}
	f := domain.ReadEvent(in.entry, overrides, in.src.ID, in.headers, in.body)
	key := in.keyOverride
	if key == "" && f.Key != nil {
		key = *f.Key
	}
	if key == "" {
		key = "recv:" + uuid.NewString()
	}
	eventID := domain.EventIDFor(in.src.StreamID, key)
	body, attachments, err := s.storeAttachments(ctx, in, eventID)
	if err != nil {
		return Receipt{}, err
	}
	var bodyRef any
	if body != nil {
		encoded, err := compactJSON(map[string]any{"body": body})
		if err != nil {
			return Receipt{}, err
		}
		if len(encoded) > domain.MaxInlineBodyBytes {
			ref := eventFilePath(in.src.StreamID, eventID, "body.json")
			data, err := events.PyJSON(body)
			if err != nil {
				return Receipt{}, err
			}
			if err := s.putFile(ctx, in.src.WorkspaceID, ref, []byte(data), "application/json"); err != nil {
				return Receipt{}, err
			}
			bodyRef, body = ref, nil
		}
	}
	var scheme *domain.Verification
	if in.entry.Verification != nil {
		v, err := domain.Configured(*in.entry.Verification, in.src.WebhookConfig)
		if err != nil {
			return Receipt{}, err
		}
		scheme = &v
	}
	depth, correlation, causation := s.carriedChain(ctx, in.src.ID, f)
	kind := f.Kind
	if in.kindOverride != "" {
		kind = in.kindOverride
	}
	occurred := in.receivedAt
	if f.OccurredAt != nil {
		occurred = *f.OccurredAt
	}
	headers := map[string]any{}
	for k, v := range domain.WithoutCredentials(in.headers, scheme) {
		headers[k] = v
	}
	srcID, slug := in.src.ID, in.entry.Slug
	ok, err := s.Append(ctx, sess, domain.Event{
		ID: eventID, Kind: kind, Source: "/sources/" + in.src.ID, Subject: f.SessionKey, OccurredAt: occurred,
		CorrelationID: correlation, CausationID: causation,
		Data:     map[string]any{"headers": headers, "body": body, "body_ref": bodyRef},
		StreamID: in.src.StreamID, WorkspaceID: in.src.WorkspaceID, CreatedBy: in.src.CreatedBy, EventKey: key,
		ReceivedAt: in.receivedAt, Depth: depth, SourceID: &srcID, SourceType: &slug, SessionKey: f.SessionKey,
		Sender: f.Sender, Attachments: attachments,
	})
	if err != nil {
		return Receipt{}, err
	}
	return Receipt{EventID: eventID, Appended: ok}, nil
}

func (s *Service) carriedChain(ctx context.Context, sourceID string, f domain.EventFields) (int, *string, *string) {
	depth := 0
	if f.Depth != nil {
		if d, ok := domain.CarriedDepth(*f.Depth, s.d.Settings.ForwardDepth); ok {
			depth = d
		} else {
			s.log.WarnContext(ctx, "Source names a depth that is not a count; the event starts a chain", "source_id", sourceID, "depth", *f.Depth)
		}
	}
	ids := make([]*string, 2)
	for i, v := range []*string{f.CorrelationID, f.CausationID} {
		if v == nil {
			continue
		}
		if id, ok := domain.ChainID(*v); ok {
			ids[i] = &id
		} else {
			s.log.WarnContext(ctx, "Source names a chain id that is not a UUID; ignored", "source_id", sourceID, "value", *v)
		}
	}
	return depth, ids[0], ids[1]
}

func workspaceOf(src domain.Source) (scope.Workspace, error) {
	return scope.NewWorkspace(src.WorkspaceID, "")
}

// SourceCredentials is read_source_credentials: every credential of a source as text, referenced
// workspace secrets resolved; empty when none are stored. userID is the source's creator.
func (s *Service) SourceCredentials(ctx context.Context, ws scope.Workspace, userID, slug, credentialKey string) (map[string]string, error) {
	var out map[string]string
	err := s.read(ctx, ws, func(sess db.Session) error {
		var err error
		out, err = s.sourceCredentials(ctx, sess, userID, slug, credentialKey)
		return err
	})
	return out, err
}

func (s *Service) sourceCredentials(ctx context.Context, sess db.Session, userID, slug, credentialKey string) (map[string]string, error) {
	what := fmt.Sprintf("credentials of %s source %s", slug, credentialKey)
	m := s.d.Secrets.Manager(sess, userID)
	get := func(name, what string) (string, error) {
		v, err := m.Get(ctx, name)
		if errors.Is(err, ksecrets.ErrNotFound) {
			return "", nil
		}
		if err != nil {
			s.log.ErrorContext(ctx, "Reading source credentials from the secret store failed", "error", err.Error())
			return "", &credentialsError{unreachable: true, msg: what, cause: err}
		}
		return v, nil
	}
	raw, err := get(CredentialSecretName(slug, credentialKey), what)
	if err != nil || raw == "" {
		return map[string]string{}, err
	}
	dec := json.NewDecoder(strings.NewReader(raw))
	dec.UseNumber()
	var stored any
	if err := dec.Decode(&stored); err != nil {
		s.log.ErrorContext(ctx, "Stored source credentials are not JSON", "what", what)
		return nil, &credentialsError{msg: what, cause: err}
	}
	obj, ok := stored.(map[string]any)
	if !ok {
		return nil, &credentialsError{msg: "stored " + what + " are not an object"}
	}
	out := make(map[string]string, len(obj))
	for k, v := range obj {
		switch x := v.(type) {
		case map[string]any:
			name, _ := x["secret_name"].(string)
			if name == "" {
				return nil, &credentialsError{msg: fmt.Sprintf("%s of %s names no secret", k, what)}
			}
			secret, err := get(name, fmt.Sprintf("the secret %s of %s names", k, what))
			if err != nil {
				return nil, err
			}
			if secret == "" {
				return nil, &credentialsError{msg: fmt.Sprintf("the secret %s of %s names has no value", k, what)}
			}
			out[k] = secret
		case nil:
		case string:
			if x != "" {
				out[k] = x
			}
		default:
			if text, ok := domain.Scalar(x); ok {
				out[k] = text
			} else if b, err := json.Marshal(x); err == nil {
				out[k] = string(b)
			}
		}
	}
	return out, nil
}

// DecodeJSON is json.loads strictly: numbers kept exact, NaN and Infinity refused (Go never
// accepts them), one value only.
func DecodeJSON(raw []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	if dec.More() {
		return nil, errors.New("extra data after the JSON value")
	}
	return v, nil
}

// IngestPolled is poll_intake._ingest_item for one item the pollers fetched: the source in any
// workspace, its catalog entry, and the item ingested as a webhook body is, with no headers.
// A deleted source or a gone stream drops the item (nil).
func (s *Service) IngestPolled(ctx context.Context, sourceID string, item json.RawMessage, receivedAt time.Time) error {
	body, err := DecodeJSON(item)
	if err != nil {
		return fmt.Errorf("%w: item is not JSON: %w", ErrMalformedItem, err)
	}
	return s.ingestPolled(ctx, sourceID, body, receivedAt, "", "")
}

// IngestGap records that a poll source may have missed events: a source.gap event keyed by the
// time it was noticed, body {"reason": reason}.
func (s *Service) IngestGap(ctx context.Context, sourceID, reason string, receivedAt time.Time) error {
	s.log.WarnContext(ctx, "Source reported a gap", "source_id", sourceID, "reason", reason)
	return s.ingestPolled(ctx, sourceID, map[string]any{"reason": reason}, receivedAt, domain.GapKind, "gap:"+events.PyISO(receivedAt))
}

func (s *Service) ingestPolled(ctx context.Context, sourceID string, body any, receivedAt time.Time, kind, key string) error {
	id, err := uuid.Parse(sourceID)
	if err != nil {
		return fmt.Errorf("%w: source id %q is not a UUID", ErrMalformedItem, sourceID)
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return err
	}
	src, ok, err := s.ss.SourceByID(ctx, q, id)
	release()
	if err != nil {
		return err
	}
	if !ok {
		s.log.InfoContext(ctx, "Polled item of a deleted source dropped", "source_id", sourceID)
		return nil
	}
	if src.SourceType == nil || *src.SourceType == "" {
		return fmt.Errorf("%w: source %s names no source type", ErrMalformedItem, src.ID)
	}
	entry, found, err := s.SourceTypeEntry(ctx, *src.SourceType)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("%w: source type %s is not in the catalog", ErrMalformedItem, domain.PyRepr(*src.SourceType))
	}
	ws, err := workspaceOf(src)
	if err != nil {
		return err
	}
	var r Receipt
	err = s.read(ctx, ws, func(sess db.Session) error {
		r, err = s.ingest(ctx, sess, intake{src: src, entry: entry, body: body, headers: map[string]string{},
			receivedAt: receivedAt.UTC(), kindOverride: kind, keyOverride: key})
		return err
	})
	if errors.Is(err, domain.ErrStreamNotFound) {
		s.log.InfoContext(ctx, "Polled item of a source whose stream is gone dropped", "source_id", src.ID)
		return nil
	}
	if err == nil && !r.Appended {
		s.log.DebugContext(ctx, "Polled item was a repeat", "source_id", src.ID, "event_id", r.EventID)
	}
	return err
}
