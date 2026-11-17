package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/streams"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

// channelIcons is CHANNEL_ICON_NAMESPACE.
const channelIcons = "channels"

// mountSources registers sources and source types when the catalog and secrets are wired.
func mountSources(base chi.Router, w *gen.ServerInterfaceWrapper, s *Server) {
	if !s.svc.SourcesReady() {
		return
	}
	p := httpx.WorkspacePrefix + "/streams"
	base.Get(p+"/source-types", w.ListSourceTypesV1StreamsSourceTypesGet)
	base.Get(p+"/{stream_id}/sources", w.ListSourcesV1StreamsStreamIdSourcesGet)
	base.Post(p+"/{stream_id}/sources", w.AddSourceV1StreamsStreamIdSourcesPost)
	base.Patch(p+"/{stream_id}/sources/{source_id}", w.PatchSourceV1StreamsStreamIdSourcesSourceIdPatch)
	base.Delete(p+"/{stream_id}/sources/{source_id}", w.DeleteSourceV1StreamsStreamIdSourcesSourceIdDelete)
}

type sendersJSON struct {
	Allow string   `json:"allow"`
	IDs   []string `json:"ids"`
}

type sourceJSON struct {
	ID             string         `json:"id"`
	Kind           string         `json:"kind"`
	SourceType     *string        `json:"source_type"`
	WebhookID      *string        `json:"webhook_id"`
	WebhookURL     *string        `json:"webhook_url"`
	EventTemplates map[string]any `json:"event_templates"`
	PolledAt       *time.Time     `json:"polled_at"`
	PollError      *string        `json:"poll_error"`
	Registered     bool           `json:"registered"`
	Senders        *sendersJSON   `json:"senders"`
	SendersSetBy   *string        `json:"senders_set_by"`
	CreatedAt      time.Time      `json:"created_at"`
}

type sourceCreatedJSON struct {
	sourceJSON
	Issued map[string]string `json:"issued"`
}

func (s *Server) sourceOut(src domain.Source) sourceJSON {
	out := sourceJSON{
		ID: src.ID, Kind: src.Kind, SourceType: src.SourceType, WebhookID: src.WebhookID,
		EventTemplates: src.EventTemplates, PollError: src.PollError, Registered: s.svc.Registered(src),
		CreatedAt: src.CreatedAt.UTC(),
	}
	if src.WebhookID != nil && *src.WebhookID != "" {
		u := s.svc.PublicWebhookURL(*src.WebhookID)
		out.WebhookURL = &u
	}
	if src.PolledAt != nil {
		t := src.PolledAt.UTC()
		out.PolledAt = &t
	}
	if rec, ok := domain.SendersRecordOf(src.Senders); ok {
		ids := rec.IDs
		if ids == nil {
			ids = []string{}
		}
		out.Senders = &sendersJSON{Allow: rec.Allow, IDs: ids}
		out.SendersSetBy = rec.By
	}
	return out
}

type sourceTypeTemplatesJSON struct {
	Kind       domain.Template `json:"kind"`
	Key        domain.Template `json:"key"`
	SessionKey domain.Template `json:"session_key"`
	Sender     domain.Template `json:"sender"`
	OccurredAt domain.Template `json:"occurred_at"`
}

type sourceTypeJSON struct {
	Slug               string                  `json:"slug"`
	Name               string                  `json:"name"`
	Description        string                  `json:"description"`
	Icon               string                  `json:"icon"`
	IconURL            *string                 `json:"icon_url"`
	Delivery           string                  `json:"delivery"`
	Credentials        []domain.SourceField    `json:"credentials"`
	Config             []domain.SourceField    `json:"config"`
	Events             []string                `json:"events"`
	Event              sourceTypeTemplatesJSON `json:"event"`
	VerificationScheme *string                 `json:"verification_scheme"`
	VerificationHeader *string                 `json:"verification_header"`
	ContinuesSessions  bool                    `json:"continues_sessions"`
	AdmitsSenders      bool                    `json:"admits_senders"`
	Replies            bool                    `json:"replies"`
	RegistersWebhook   bool                    `json:"registers_webhook"`
}

func iconURL(apiURL, icon string) *string {
	if icon == "" {
		return nil
	}
	if strings.HasPrefix(icon, "http://") || strings.HasPrefix(icon, "https://") {
		return &icon
	}
	u := strings.TrimRight(apiURL, "/") + "/static/icons/" + channelIcons + "/" + icon + ".svg"
	return &u
}

func (s *Server) sourceTypeOut(e domain.SourceTypeEntry) sourceTypeJSON {
	out := sourceTypeJSON{
		Slug: e.Slug, Name: e.Name, Description: e.Description, Icon: e.Icon, IconURL: iconURL(s.svc.APIURL(), e.Icon),
		Delivery: e.Delivery, Credentials: e.Credentials, Config: e.Config, Events: e.Events,
		Event: sourceTypeTemplatesJSON{Kind: e.Event.Kind, Key: e.Event.Key, SessionKey: e.Event.SessionKey,
			Sender: e.Event.Sender, OccurredAt: e.Event.OccurredAt},
		ContinuesSessions: e.ContinuesSessions(), AdmitsSenders: e.Admission != nil, Replies: e.Reply != nil,
		RegistersWebhook: e.Registration != nil,
	}
	if v := e.Verification; v != nil {
		scheme := v.Scheme
		out.VerificationScheme = &scheme
		out.VerificationHeader = v.Header
	}
	return out
}

// sourceError renders what only the source routes answer: 422 for a request the entry cannot
// take, 403 for a secret the caller may not use, 422 for a senders choice pydantic refuses.
func sourceError(err error) error {
	var se *domain.StreamError
	if errors.As(err, &se) && errors.Is(se.Kind, domain.ErrSourceRefused) {
		return httpx.HTTPError(http.StatusUnprocessableEntity, se.Msg)
	}
	if errors.Is(err, service.ErrSecretForbidden) {
		return httpx.HTTPError(http.StatusForbidden, strings.TrimPrefix(err.Error(), service.ErrSecretForbidden.Error()+": "))
	}
	return err
}

func unprocessable(err error) error {
	var inv *domain.ValidationError
	if errors.As(err, &inv) {
		return httpx.HTTPError(http.StatusUnprocessableEntity, inv.Msg)
	}
	return err
}

func (s *Server) ListSourceTypesV1StreamsSourceTypesGet(ctx context.Context, _ gen.ListSourceTypesV1StreamsSourceTypesGetRequestObject) (gen.ListSourceTypesV1StreamsSourceTypesGetResponseObject, error) {
	entries, err := s.svc.SourceTypeEntries(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]sourceTypeJSON, 0, len(entries))
	for _, e := range entries {
		out = append(out, s.sourceTypeOut(e))
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) ListSourcesV1StreamsStreamIdSourcesGet(ctx context.Context, req gen.ListSourcesV1StreamsStreamIdSourcesGetRequestObject) (gen.ListSourcesV1StreamsStreamIdSourcesGetResponseObject, error) {
	rows, err := s.svc.ListSources(ctx, req.StreamId.String())
	if err != nil {
		return nil, err
	}
	out := make([]sourceJSON, 0, len(rows))
	for _, r := range rows {
		out = append(out, s.sourceOut(r))
	}
	return response{status: http.StatusOK, body: out}, nil
}

func credentialOf(key string, v gen.SourceCreate_Credentials_AdditionalProperties) (service.Credential, error) {
	raw, err := v.MarshalJSON()
	if err != nil {
		return service.Credential{}, err
	}
	var text string
	if json.Unmarshal(raw, &text) == nil {
		return service.Credential{Value: &text}, nil
	}
	var ref struct {
		SecretID string `json:"secret_id"`
	}
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	if dec.Decode(&ref) != nil || ref.SecretID == "" {
		return service.Credential{}, httpx.HTTPError(http.StatusUnprocessableEntity,
			"credentials."+key+": Input should be a valid string or {secret_id}")
	}
	id, err := domain.CanonicalUUID(ref.SecretID)
	if err != nil {
		return service.Credential{}, httpx.HTTPError(http.StatusUnprocessableEntity,
			"credentials."+key+".secret_id: Input should be a valid UUID")
	}
	return service.Credential{SecretID: &id}, nil
}

func sendersOf(g gen.Senders) (domain.Senders, error) {
	m := map[string]any{"allow": string(g.Allow)}
	if g.Ids != nil {
		ids := make([]any, len(*g.Ids))
		for i, id := range *g.Ids {
			ids[i] = id
		}
		m["ids"] = ids
	}
	sd, err := domain.ParseSenders(m)
	return sd, unprocessable(err)
}

func newSource(b *gen.SourceCreate) (service.NewSource, error) {
	n := service.NewSource{SourceType: b.SourceType, Kind: domain.SourceWebhook,
		Credentials: map[string]service.Credential{}, Config: map[string]string{}}
	if l := len([]rune(b.SourceType)); l < 1 || l > 50 {
		return n, httpx.HTTPError(http.StatusUnprocessableEntity, "source_type: String should have 1 to 50 characters")
	}
	if b.Kind != nil {
		n.Kind = string(*b.Kind)
		if n.Kind != domain.SourceWebhook && n.Kind != domain.SourcePoll && n.Kind != domain.SourcePlatform {
			return n, httpx.HTTPError(http.StatusUnprocessableEntity, "kind: Input should be 'webhook', 'poll' or 'platform'")
		}
	}
	if b.Credentials != nil {
		for k, v := range *b.Credentials {
			c, err := credentialOf(k, v)
			if err != nil {
				return n, err
			}
			n.Credentials[k] = c
		}
	}
	if b.Config != nil {
		n.Config = *b.Config
	}
	if b.EventTemplates != nil {
		raw, err := json.Marshal(b.EventTemplates)
		if err != nil {
			return n, err
		}
		var m map[string]any
		if err := json.Unmarshal(raw, &m); err != nil {
			return n, err
		}
		o, err := domain.ParseEventOverrides(m)
		if err != nil {
			return n, unprocessable(err)
		}
		n.EventTemplates = &o
	}
	if b.Senders != nil {
		sd, err := sendersOf(*b.Senders)
		if err != nil {
			return n, err
		}
		n.Senders = &sd
	}
	return n, nil
}

func (s *Server) AddSourceV1StreamsStreamIdSourcesPost(ctx context.Context, req gen.AddSourceV1StreamsStreamIdSourcesPostRequestObject) (gen.AddSourceV1StreamsStreamIdSourcesPostResponseObject, error) {
	if req.Body == nil {
		return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "request body is required")
	}
	n, err := newSource(req.Body)
	if err != nil {
		return nil, err
	}
	src, issued, err := s.svc.AddSource(ctx, req.StreamId.String(), n)
	if err != nil {
		return nil, sourceError(err)
	}
	return response{status: http.StatusCreated, body: sourceCreatedJSON{sourceJSON: s.sourceOut(src), Issued: issued}}, nil
}

func (s *Server) PatchSourceV1StreamsStreamIdSourcesSourceIdPatch(ctx context.Context, req gen.PatchSourceV1StreamsStreamIdSourcesSourceIdPatchRequestObject) (gen.PatchSourceV1StreamsStreamIdSourcesSourceIdPatchResponseObject, error) {
	if req.Body == nil {
		return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "request body is required")
	}
	sd, err := sendersOf(req.Body.Senders)
	if err != nil {
		return nil, err
	}
	src, err := s.svc.SetSourceSenders(ctx, req.StreamId.String(), req.SourceId.String(), sd)
	if err != nil {
		return nil, sourceError(err)
	}
	return response{status: http.StatusOK, body: s.sourceOut(src)}, nil
}

func (s *Server) DeleteSourceV1StreamsStreamIdSourcesSourceIdDelete(ctx context.Context, req gen.DeleteSourceV1StreamsStreamIdSourcesSourceIdDeleteRequestObject) (gen.DeleteSourceV1StreamsStreamIdSourcesSourceIdDeleteResponseObject, error) {
	if err := s.svc.DeleteSource(ctx, req.StreamId.String(), req.SourceId.String()); err != nil {
		return nil, sourceError(err)
	}
	return response{status: http.StatusNoContent}, nil
}

func (x response) VisitListSourceTypesV1StreamsSourceTypesGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}

func (x response) VisitListSourcesV1StreamsStreamIdSourcesGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}

func (x response) VisitAddSourceV1StreamsStreamIdSourcesPostResponse(w http.ResponseWriter) error {
	return x.write(w)
}

func (x response) VisitPatchSourceV1StreamsStreamIdSourcesSourceIdPatchResponse(w http.ResponseWriter) error {
	return x.write(w)
}

func (x response) VisitDeleteSourceV1StreamsStreamIdSourcesSourceIdDeleteResponse(w http.ResponseWriter) error {
	return x.write(w)
}
