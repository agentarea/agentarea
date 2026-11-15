package service

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// SecretConsumer is the consumer type a source's secret references carry.
const SecretConsumer = "stream_source"

// ErrSecretForbidden is a picked workspace secret the caller may not use (403).
var ErrSecretForbidden = errors.New("secret not usable")

// CredentialSecretName is where a source's credentials are stored.
func CredentialSecretName(slug, credentialKey string) string {
	return "channel_cred:" + slug + ":" + credentialKey
}

func tokenURLSafe(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

// IssueCredential is a value the platform generates for an issued field left empty.
func IssueCredential(f domain.SourceField) (string, error) {
	if f.Format == "whsec" {
		b := make([]byte, 32)
		if _, err := rand.Read(b); err != nil {
			return "", err
		}
		return "whsec_" + base64.StdEncoding.EncodeToString(b), nil
	}
	return tokenURLSafe(32)
}

// SourcesReady is whether the source routes have their ports: catalog, secrets and the secret catalog.
func (s *Service) SourcesReady() bool {
	return s.d.SourceTypes != nil && s.d.Secrets != nil && s.d.SecretCatalog != nil
}

// WebhooksReady is whether the webhook sink has its ports: catalog, secrets, bus and dedup.
func (s *Service) WebhooksReady() bool {
	return s.d.SourceTypes != nil && s.d.Secrets != nil && s.d.Bus != nil && s.d.Dedup != nil
}

// SourceTypeEntries is list_entries: one valid entry per slug (the highest-priority registry's), by name.
func (s *Service) SourceTypeEntries(ctx context.Context) ([]domain.SourceTypeEntry, error) {
	rows, err := s.d.SourceTypes.SourceTypeRows(ctx)
	if err != nil {
		return nil, err
	}
	entries := make([]domain.SourceTypeEntry, 0, len(rows))
	for _, r := range rows {
		e, err := domain.ParseSourceTypeEntry(r.Spec)
		if err != nil {
			s.log.ErrorContext(ctx, "Catalog source type is not a valid entry", "slug", r.Slug, "error", err.Error())
			continue
		}
		entries = append(entries, e)
	}
	return domain.EntriesByName(entries), nil
}

// SourceTypeEntry is the first valid entry of slug by registry priority; false when none.
func (s *Service) SourceTypeEntry(ctx context.Context, slug string) (domain.SourceTypeEntry, bool, error) {
	rows, err := s.d.SourceTypes.SourceTypeRowsBySlug(ctx, slug)
	if err != nil {
		return domain.SourceTypeEntry{}, false, err
	}
	for _, r := range rows {
		e, err := domain.ParseSourceTypeEntry(r.Spec)
		if err != nil {
			s.log.ErrorContext(ctx, "Catalog source type is not a valid entry", "slug", r.Slug, "error", err.Error())
			continue
		}
		return e, true, nil
	}
	return domain.SourceTypeEntry{}, false, nil
}

func (s *Service) entryFor(ctx context.Context, slug string) (domain.SourceTypeEntry, error) {
	e, ok, err := s.SourceTypeEntry(ctx, slug)
	if err != nil {
		return e, err
	}
	if !ok {
		return e, domain.Refused(fmt.Sprintf("Unknown source type %s; see GET /streams/source-types", domain.PyRepr(slug)))
	}
	return e, nil
}

// PublicWebhookURL is where a provider posts a webhook source's events.
func (s *Service) PublicWebhookURL(webhookID string) string {
	base := s.d.WebhookURL
	if base == "" {
		base = s.d.APIURL
	}
	return strings.TrimRight(base, "/") + "/webhooks/" + webhookID
}

// Registered is whether the provider was pointed at the source's current webhook URL.
func (s *Service) Registered(src domain.Source) bool {
	return src.WebhookID != nil && *src.WebhookID != "" && src.RegisteredURL != nil &&
		*src.RegisteredURL == s.PublicWebhookURL(*src.WebhookID)
}

// ListSources is list_sources behind requires("read", "stream").
func (s *Service) ListSources(ctx context.Context, streamID string) ([]domain.Source, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.perms.Require(ctx, c, "read", "stream", streamID); err != nil {
		return nil, err
	}
	u, err := uuid.Parse(streamID)
	if err != nil {
		return []domain.Source{}, nil
	}
	var out []domain.Source
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		out, err = s.ss.ListSources(ctx, sess, u)
		return err
	})
	return out, err
}

// Credential is one credential sent for a source: a value, or a workspace secret by id.
type Credential struct {
	Value    *string
	SecretID *string
}

// NewSource is a SourceCreate.
type NewSource struct {
	SourceType     string
	Kind           string
	Credentials    map[string]Credential
	Config         map[string]string
	EventTemplates *domain.EventOverrides
	Senders        *domain.Senders
}

func pyList(items []string) string {
	q := make([]string, len(items))
	for i, s := range items {
		q[i] = domain.PyRepr(s)
	}
	return "[" + strings.Join(q, ", ") + "]"
}

func isWhsec(v string) bool {
	rest, ok := strings.CutPrefix(v, "whsec_")
	if !ok {
		return false
	}
	b, err := base64.StdEncoding.Strict().DecodeString(rest)
	return err == nil && len(b) >= 24 && len(b) <= 64
}

// checkSource refuses what the entry cannot take, before anything is written.
func checkSource(e domain.SourceTypeEntry, n NewSource) error {
	if !e.Accepts(n.Kind) {
		return domain.Refused(fmt.Sprintf("%s sources are %s, not %s", e.Name, e.Delivery, n.Kind))
	}
	type given struct {
		value *string
	}
	creds := map[string]given{}
	for k, c := range n.Credentials {
		creds[k] = given{value: c.Value}
	}
	conf := map[string]given{}
	for k, v := range n.Config {
		conf[k] = given{value: &v}
	}
	for _, g := range []struct {
		given    map[string]given
		declared []domain.SourceField
		kind     string
	}{{creds, e.Credentials, "credential"}, {conf, e.Config, "setting"}} {
		known := map[string]bool{}
		names := make([]string, 0, len(g.declared))
		for _, f := range g.declared {
			if !known[f.Key] {
				names = append(names, f.Key)
			}
			known[f.Key] = true
		}
		var unknown []string
		for k := range g.given {
			if !known[k] {
				unknown = append(unknown, k)
			}
		}
		if len(unknown) > 0 {
			sort.Strings(unknown)
			sort.Strings(names)
			return domain.Refused(fmt.Sprintf("%s has no %s %s; it takes %s", e.Name, g.kind, strings.Join(unknown, ", "), pyList(names)))
		}
		for _, f := range g.declared {
			v, has := g.given[f.Key]
			if has && v.value != nil && *v.value == "" {
				return domain.Refused(f.Key + " is empty")
			}
			if f.Required && !has {
				return domain.Refused(fmt.Sprintf("%s needs %s", e.Name, f.Key))
			}
			if f.Format == "whsec" && has && v.value != nil && !isWhsec(*v.value) {
				return domain.Refused(f.Key + " must be whsec_ and the base64 of 24 to 64 bytes")
			}
		}
	}
	if n.Senders != nil && e.Admission == nil {
		return domain.Refused(e.Name + " sources let anyone through; they take no senders")
	}
	if e.Verification != nil {
		cfg := make(map[string]any, len(n.Config))
		for k, v := range n.Config {
			cfg[k] = v
		}
		if _, err := domain.Configured(*e.Verification, cfg); err != nil {
			return domain.Refused(fmt.Sprintf("%s cannot verify with these settings: %s", e.Name, err.Error()))
		}
	}
	return nil
}

// usableSecret is the name of a workspace secret the caller may wire in; its value is not read.
func (s *Service) usableSecret(ctx context.Context, c authn.Caller, sess db.Session, secretID, field string) (string, error) {
	sec, err := s.d.SecretCatalog(c.Workspace, actorOf(c)).GetForUse(ctx, secretID)
	switch {
	case errors.Is(err, ksecrets.ErrNotFound):
		return "", domain.Refused(fmt.Sprintf("The secret chosen for %s is not in this workspace", field))
	case errors.Is(err, ksecrets.ErrManaged):
		return "", domain.Refused(fmt.Sprintf("The secret chosen for %s must be a workspace secret", field))
	case errors.Is(err, ksecrets.ErrAccessDenied):
		return "", fmt.Errorf("%w: %s", ErrSecretForbidden, err.Error())
	case err != nil:
		return "", err
	}
	has, err := s.d.Secrets.Manager(sess, c.UserID).Has(ctx, sec.Name)
	if err != nil {
		return "", err
	}
	if !has {
		return "", domain.Refused(fmt.Sprintf("The secret chosen for %s has no value", field))
	}
	return sec.Name, nil
}

func actorOf(c authn.Caller) ksecrets.Actor {
	return ksecrets.Actor{UserID: c.UserID, GraphSubject: c.GraphSubject()}
}

// AddSource is create_source behind requires("edit", "stream"): every check runs before anything
// is written; an issued credential left out is generated and returned this once.
func (s *Service) AddSource(ctx context.Context, streamID string, n NewSource) (domain.Source, map[string]string, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Source{}, nil, err
	}
	if err := s.perms.Require(ctx, c, "edit", "stream", streamID); err != nil {
		return domain.Source{}, nil, err
	}
	if n.Kind == domain.SourcePlatform {
		return domain.Source{}, nil, domain.Refused("kind: Value error, platform sources are the platform's; add a webhook or poll source")
	}
	e, err := s.entryFor(ctx, n.SourceType)
	if err != nil {
		return domain.Source{}, nil, err
	}
	if err := checkSource(e, n); err != nil {
		return domain.Source{}, nil, err
	}
	config := make(map[string]any, len(n.Config))
	for k, v := range n.Config {
		config[k] = v
	}
	if e.SpeaksMCPEvents() {
		if config, err = s.mcpEventsConfig(ctx, c, n); err != nil {
			return domain.Source{}, nil, err
		}
	}
	var templates map[string]any
	if n.EventTemplates != nil {
		templates = n.EventTemplates.Dump()
	}
	var out domain.Source
	issued := map[string]string{}
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		stored := map[string]any{}
		var refs []ksecrets.Reference
		keys := make([]string, 0, len(n.Credentials))
		for k := range n.Credentials {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			cred := n.Credentials[k]
			if cred.SecretID == nil {
				stored[k] = *cred.Value
				continue
			}
			name, err := s.usableSecret(ctx, c, sess, *cred.SecretID, k)
			if err != nil {
				return err
			}
			stored[k] = map[string]any{"secret_name": name}
			refs = append(refs, ksecrets.Reference{SecretID: *cred.SecretID, Field: k})
		}
		for _, f := range e.Credentials {
			if _, has := stored[f.Key]; f.Issued && !has {
				v, err := IssueCredential(f)
				if err != nil {
					return err
				}
				issued[f.Key] = v
				stored[f.Key] = v
			}
		}
		st, err := s.getStream(ctx, sess, streamID)
		if err != nil {
			return err
		}
		if st.Kind == domain.StreamPlatform {
			return domain.Fail(domain.ErrManagedByPlatform,
				"Only the platform writes to the platform stream; add sources to another stream")
		}
		id := uuid.NewString()
		src := domain.Source{
			ID: id, StreamID: st.ID, Kind: n.Kind, SourceType: &e.Slug, WebhookConfig: config,
			CredentialKey: &id, EventTemplates: templates, CreatedBy: c.UserID,
			Senders: domain.SendersToStore(e.Admission != nil, n.Senders, c.UserID),
		}
		if n.Kind == domain.SourceWebhook {
			wid, err := tokenURLSafe(16)
			if err != nil {
				return err
			}
			src.WebhookID = &wid
		}
		if out, err = s.ss.InsertSource(ctx, sess, src, s.now()); err != nil {
			return err
		}
		body, err := json.Marshal(stored)
		if err != nil {
			return err
		}
		if err := s.d.Secrets.Manager(sess, c.UserID).Set(ctx, CredentialSecretName(e.Slug, id), string(body)); err != nil {
			return err
		}
		if len(refs) > 0 {
			return s.d.Secrets.StageReferences(ctx, sess, SecretConsumer, id, refs)
		}
		return nil
	})
	if err != nil {
		return domain.Source{}, nil, err
	}
	return out, issued, nil
}

// SetSourceSenders is update_source behind requires("edit", "stream"): who may write to a source
// whose type admits senders; the caller answers for the choice.
func (s *Service) SetSourceSenders(ctx context.Context, streamID, sourceID string, senders domain.Senders) (domain.Source, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Source{}, err
	}
	if err := s.perms.Require(ctx, c, "edit", "stream", streamID); err != nil {
		return domain.Source{}, err
	}
	stream, sid, err := sourceIDs(streamID, sourceID)
	if err != nil {
		return domain.Source{}, err
	}
	var out domain.Source
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		src, ok, err := s.ss.GetSource(ctx, sess, stream, sid)
		if err != nil {
			return err
		}
		if !ok {
			return domain.SourceNotFound(sourceID)
		}
		slug := ""
		if src.SourceType != nil {
			slug = *src.SourceType
		}
		e, err := s.entryFor(ctx, slug)
		if err != nil {
			return err
		}
		if e.Admission == nil {
			return domain.Refused(e.Name + " sources let anyone through; they take no senders")
		}
		out, ok, err = s.ss.SetSenders(ctx, sess, stream, sid, domain.SendersToStore(true, &senders, c.UserID), s.now())
		if err == nil && !ok {
			err = domain.SourceNotFound(sourceID)
		}
		return err
	})
	return out, err
}

func sourceIDs(streamID, sourceID string) (uuid.UUID, uuid.UUID, error) {
	stream, err := uuid.Parse(streamID)
	if err != nil {
		return uuid.UUID{}, uuid.UUID{}, domain.SourceNotFound(sourceID)
	}
	sid, err := uuid.Parse(sourceID)
	if err != nil {
		return uuid.UUID{}, uuid.UUID{}, domain.SourceNotFound(sourceID)
	}
	return stream, sid, nil
}

// DeleteSource removes a source and releases its credentials; its events stay.
func (s *Service) DeleteSource(ctx context.Context, streamID, sourceID string) error {
	c, err := callerOf(ctx)
	if err != nil {
		return err
	}
	if err := s.perms.Require(ctx, c, "edit", "stream", streamID); err != nil {
		return err
	}
	stream, sid, err := sourceIDs(streamID, sourceID)
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		src, ok, err := s.ss.GetSource(ctx, sess, stream, sid)
		if err != nil {
			return err
		}
		if !ok {
			return domain.SourceNotFound(sourceID)
		}
		if src.Kind == domain.SourcePlatform {
			return domain.Fail(domain.ErrManagedByPlatform, fmt.Sprintf("Source %s is the platform's and cannot be removed", sourceID))
		}
		deleted, err := s.ss.DeleteSource(ctx, sess, sid)
		if err != nil {
			return err
		}
		if !deleted {
			return domain.SourceNotFound(sourceID)
		}
		return s.releaseSource(ctx, sess, c, src)
	})
}

// APIURL is the public base of the API (AGENTAREA_API_URL), for icon URLs.
func (s *Service) APIURL() string { return s.d.APIURL }

// WebhookRate is the webhook deliveries a webhook id may make per minute.
func (s *Service) WebhookRate() int { return s.d.Settings.WebhookRate }
