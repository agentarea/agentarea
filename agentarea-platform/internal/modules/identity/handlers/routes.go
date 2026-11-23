package handlers

import (
	"errors"
	"io"
	"mime"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/service"
)

// Features are the routes that need a port app may not have wired yet.
type Features struct {
	Logos    bool
	Explorer bool
}

// MountRest registers the identity routes beyond the four create routes.
func MountRest(r chi.Router, errs *httpx.Errors, edge Edge, svc *service.Service, f Features) {
	s := &Server{svc: svc, edge: edge, errs: errs}
	h := func(fn func(http.ResponseWriter, *http.Request) error) http.HandlerFunc {
		return errs.Handler(fn).ServeHTTP
	}
	p := r.With(edge.Principal)
	p.Get("/v1/workspaces", h(s.listWorkspaces))
	p.Post("/v1/invitations/preview", h(s.previewInvitation))
	p.Get("/v1/me/external-identities", h(s.listLinks))
	p.Post("/v1/me/external-identities/telegram/link", h(s.startTelegramLink))
	p.Post("/v1/me/external-identities/telegram/offer/preview", h(s.previewTelegramOffer))
	p.Post("/v1/me/external-identities/telegram/offer/accept", h(s.acceptTelegramOffer))
	p.Delete("/v1/me/external-identities/{identity_id}", h(s.unlink))

	w := r.With(edge.Workspace)
	ws := httpx.WorkspacePrefix
	if f.Logos {
		w.Put(ws+"/logo", h(s.putLogo))
		w.Delete(ws+"/logo", h(s.deleteLogo))
	}
	w.Get(ws+"/invitations", h(s.listInvitations))
	w.Delete(ws+"/invitations/{invitation_id}", h(s.revokeInvitation))
	w.Get(ws+"/members", h(s.listMembers))
	w.Delete(ws+"/members/{user_id}", h(s.removeMember))
	w.Get(ws+"/api-keys/", h(s.listAPIKeys))
	w.Get(ws+"/api-keys/{token_id}", h(s.getAPIKey))
	w.Delete(ws+"/api-keys/{token_id}", h(s.revokeAPIKey))
	w.Get(ws+"/principals", h(s.resolvePrincipals))
	w.Post(ws+"/access-control/sync", h(s.sync))
	if f.Explorer {
		w.Get(ws+"/access-control/graph", h(s.graph))
		w.Get(ws+"/access-control/relationships", h(s.relationships))
		w.Post(ws+"/access-control/relationships", h(s.grant))
		w.Delete(ws+"/access-control/relationships", h(s.revokeGrant))
		w.Post(ws+"/access-control/check", h(s.check))
		w.Post(ws+"/access-control/resolve", h(s.resolve))
	}
}

func noContent(w http.ResponseWriter) error {
	w.WriteHeader(http.StatusNoContent)
	return nil
}

func writeList(w http.ResponseWriter, items []wirejson.Object) error {
	list := make([]any, 0, len(items))
	for _, o := range items {
		list = append(list, o)
	}
	raw, err := wirejson.Marshal(list, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(http.StatusOK)
	_, err = w.Write(raw)
	return err
}

// naiveISO is a naive datetime as pydantic renders it: no offset.
func naiveISO(t time.Time) string { return strings.TrimSuffix(utcISO(t), "Z") }

func strOrNil(p *string) any {
	if p == nil {
		return nil
	}
	return *p
}

func pathUUID(r *http.Request, name string) (uuid.UUID, error) {
	id, fe := httpx.ValidateUUID(chi.URLParam(r, name), "path", name)
	if fe != nil {
		return uuid.UUID{}, httpx.Validation(*fe)
	}
	return uuid.MustParse(id), nil
}

// isAdmin is is_workspace_admin through the edge's admission.
func (s *Server) isAdmin(r *http.Request) (bool, error) {
	err := s.edge.Admin(r.Context())
	if errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		return false, nil
	}
	return err == nil, err
}

func workspaceObject(v service.WorkspaceView) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: v.ID}, {Key: "slug", Value: v.Slug}, {Key: "name", Value: v.Name},
		{Key: "owner_user_id", Value: v.OwnerUserID}, {Key: "can_administer", Value: v.CanAdminister},
		{Key: "logo_url", Value: strOrNil(v.LogoURL)},
	}
}

func (s *Server) listWorkspaces(w http.ResponseWriter, r *http.Request) error {
	p, err := principal(r.Context())
	if err != nil {
		return err
	}
	views, err := s.svc.ListWorkspaces(r.Context(), p)
	if err != nil {
		return err
	}
	out := make([]wirejson.Object, 0, len(views))
	for _, v := range views {
		out = append(out, workspaceObject(v))
	}
	return writeList(w, out)
}

// logoFile is FastAPI's File(...) for "file": the last part of that name,
// read to LogoMaxBytes+1 bytes.
func logoFile(r *http.Request) ([]byte, error) {
	missing := httpx.Validation(httpx.Missing("body", "file"))
	notFile := httpx.Validation(httpx.ValueError("Expected UploadFile, received: <class 'str'>", "body", "file"))
	media, _, _ := mime.ParseMediaType(r.Header.Get("Content-Type"))
	switch media {
	case "multipart/form-data":
	case "application/x-www-form-urlencoded":
		if err := r.ParseForm(); err != nil {
			return nil, httpx.HTTPError(http.StatusBadRequest, "There was an error parsing the body")
		}
		if r.PostForm.Has("file") {
			return nil, notFile
		}
		return nil, missing
	default:
		return nil, missing
	}
	mr, err := r.MultipartReader()
	if err != nil {
		return nil, httpx.HTTPError(http.StatusBadRequest, "There was an error parsing the body")
	}
	var data []byte
	found, isFile := false, false
	for {
		part, err := mr.NextPart()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, httpx.HTTPError(http.StatusBadRequest, "There was an error parsing the body")
		}
		if part.FormName() != "file" {
			if _, err := io.Copy(io.Discard, part); err != nil {
				return nil, err
			}
			continue
		}
		found, isFile = true, part.FileName() != ""
		if data, err = io.ReadAll(io.LimitReader(part, domain.LogoMaxBytes+1)); err != nil {
			return nil, err
		}
		if _, err := io.Copy(io.Discard, part); err != nil {
			return nil, err
		}
	}
	switch {
	case !found:
		return nil, missing
	case !isFile:
		return nil, notFile
	}
	return data, nil
}

func (s *Server) putLogo(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	if err := s.edge.Admin(r.Context()); err != nil {
		return err
	}
	data, err := logoFile(r)
	if err != nil {
		return err
	}
	v, err := s.svc.SetLogo(r.Context(), c, data)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, workspaceObject(v))
}

func (s *Server) deleteLogo(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	if err := s.edge.Admin(r.Context()); err != nil {
		return err
	}
	v, err := s.svc.RemoveLogo(r.Context(), c)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, workspaceObject(v))
}

func invitationObject(inv domain.Invitation, inviter *string) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: inv.ID},
		{Key: "workspace_id", Value: inv.WorkspaceID},
		{Key: "email", Value: strOrNil(inv.Email)},
		{Key: "invited_by", Value: inv.InvitedBy},
		{Key: "invited_by_display_name", Value: strOrNil(inviter)},
		{Key: "status", Value: inv.Status},
		{Key: "expires_at", Value: utcISO(inv.ExpiresAt)},
		{Key: "accepted_at", Value: utcISOPtr(inv.AcceptedAt)},
		{Key: "accepted_by_user_id", Value: strOrNil(inv.AcceptedByUserID)},
		{Key: "created_at", Value: utcISO(inv.CreatedAt)},
	}
}

func (s *Server) listInvitations(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	if err := s.edge.Admin(r.Context()); err != nil {
		return err
	}
	invs, err := s.svc.ListInvitations(r.Context(), c)
	if err != nil {
		return err
	}
	out := make([]wirejson.Object, 0, len(invs))
	for _, i := range invs {
		out = append(out, invitationObject(i.Invitation, i.InviterDisplayName))
	}
	return writeList(w, out)
}

func (s *Server) revokeInvitation(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	if err := s.edge.Admin(r.Context()); err != nil {
		return err
	}
	id, err := pathUUID(r, "invitation_id")
	if err != nil {
		return err
	}
	if _, err := s.svc.RevokeInvitation(r.Context(), c, id); err != nil {
		return err
	}
	return noContent(w)
}

func requiredStr(o wirejson.Object, key string, errs *[]httpx.FieldError) string {
	v, set := str(o, key, 0, 0, false, errs)
	if !set {
		*errs = append(*errs, httpx.Missing("body", key))
	}
	if v == nil {
		return ""
	}
	return *v
}

func (s *Server) previewInvitation(w http.ResponseWriter, r *http.Request) error {
	p, err := principal(r.Context())
	if err != nil {
		return err
	}
	var token string
	if err := body(r, func(o wirejson.Object, errs *[]httpx.FieldError) { token = requiredStr(o, "token", errs) }); err != nil {
		return err
	}
	pv, err := s.svc.PreviewInvitation(r.Context(), p, token)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, wirejson.Object{
		{Key: "workspace_name", Value: pv.WorkspaceName},
		{Key: "inviter_display_name", Value: strOrNil(pv.InviterDisplayName)},
		{Key: "inviter_email", Value: strOrNil(pv.InviterEmail)},
		{Key: "expires_at", Value: utcISO(pv.Invitation.ExpiresAt)},
	})
}

func (s *Server) listMembers(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	members, err := s.svc.ListMembers(r.Context(), c)
	if err != nil {
		return err
	}
	out := make([]wirejson.Object, 0, len(members))
	for _, m := range members {
		out = append(out, wirejson.Object{
			{Key: "id", Value: m.ID},
			{Key: "workspace_id", Value: m.WorkspaceID},
			{Key: "user_id", Value: m.UserID},
			{Key: "email", Value: strOrNil(m.Email)},
			{Key: "display_name", Value: strOrNil(m.DisplayName)},
			{Key: "joined_at", Value: utcISOPtr(m.JoinedAt)},
			{Key: "invitation_id", Value: strOrNil(m.InvitationID)},
			{Key: "is_owner", Value: m.IsOwner},
		})
	}
	return writeList(w, out)
}

// MaxMemberIDLength bounds the remove route's user_id path parameter.
const MaxMemberIDLength = 255

func (s *Server) removeMember(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	target := chi.URLParam(r, "user_id")
	if utf8.RuneCountInString(target) > MaxMemberIDLength {
		return httpx.Validation(httpx.StringTooLong(MaxMemberIDLength, "path", "user_id"))
	}
	revoked, err := s.svc.RemoveMember(r.Context(), c, target)
	if err != nil {
		return err
	}
	if revoked {
		return noContent(w)
	}
	return writeJSON(w, http.StatusAccepted, wirejson.Object{{Key: "status", Value: "revocation_pending"}})
}

func apiKeyObject(k domain.APIKey) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: k.ID},
		{Key: "name", Value: k.Name},
		{Key: "token_prefix", Value: k.TokenPrefix},
		{Key: "is_active", Value: k.IsActive},
		{Key: "expires_at", Value: utcISOPtr(k.ExpiresAt)},
		{Key: "access_count", Value: k.AccessCount},
		{Key: "last_accessed_at", Value: utcISOPtr(k.LastAccessedAt)},
		{Key: "created_at", Value: utcISO(k.CreatedAt)},
		{Key: "agent_id", Value: strOrNil(k.AgentID)},
	}
}

func (s *Server) listAPIKeys(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	var agent *uuid.UUID
	if vs := httpx.Query(r.URL.RawQuery)["agent_id"]; len(vs) > 0 {
		id, fe := httpx.ValidateUUID(vs[len(vs)-1], "query", "agent_id")
		if fe != nil {
			return httpx.Validation(*fe)
		}
		u := uuid.MustParse(id)
		agent = &u
	}
	admin, err := s.isAdmin(r)
	if err != nil {
		return err
	}
	keys, err := s.svc.ListAPIKeys(r.Context(), c, admin, agent)
	if err != nil {
		return err
	}
	out := make([]wirejson.Object, 0, len(keys))
	for _, k := range keys {
		out = append(out, apiKeyObject(k))
	}
	return writeList(w, out)
}

func (s *Server) getAPIKey(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	id, err := pathUUID(r, "token_id")
	if err != nil {
		return err
	}
	k, err := s.svc.GetAPIKey(r.Context(), c, func() (bool, error) { return s.isAdmin(r) }, id)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, apiKeyObject(k))
}

func (s *Server) revokeAPIKey(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	if err := authn.EnsureScope(c.Principal, authn.ScopeCredentials, "revoke API keys"); err != nil {
		return err
	}
	id, err := pathUUID(r, "token_id")
	if err != nil {
		return err
	}
	if err := s.svc.RevokeAPIKey(r.Context(), c, func() error { return s.edge.Admin(r.Context()) }, id); err != nil {
		return err
	}
	return noContent(w)
}

func (s *Server) resolvePrincipals(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	views, err := s.svc.ResolvePrincipals(r.Context(), c, httpx.Query(r.URL.RawQuery)["ids"])
	if err != nil {
		return err
	}
	out := make([]wirejson.Object, 0, len(views))
	for _, v := range views {
		out = append(out, wirejson.Object{
			{Key: "id", Value: v.ID}, {Key: "type", Value: v.Type},
			{Key: "display_name", Value: strOrNil(v.DisplayName)}, {Key: "email", Value: strOrNil(v.Email)},
		})
	}
	return writeList(w, out)
}

var botPattern = regexp.MustCompile(`^[A-Za-z0-9_]{5,32}$`)

// BotPattern is TelegramLinkRequest.bot's pattern.
const BotPattern = `^[A-Za-z0-9_]{5,32}$`

func (s *Server) startTelegramLink(w http.ResponseWriter, r *http.Request) error {
	p, err := principal(r.Context())
	if err != nil {
		return err
	}
	if err := authn.EnsureScope(p, authn.ScopeCredentials, "link a messenger account"); err != nil {
		return err
	}
	var bot string
	err = body(r, func(o wirejson.Object, errs *[]httpx.FieldError) {
		v, set := str(o, "bot", 0, 0, false, errs)
		switch {
		case !set:
			*errs = append(*errs, httpx.Missing("body", "bot"))
		case v != nil && !botPattern.MatchString(*v):
			*errs = append(*errs, httpx.StringPatternMismatch(BotPattern, "body", "bot"))
		case v != nil:
			bot = *v
		}
	})
	if err != nil {
		return err
	}
	code, err := s.svc.StartTelegramLink(r.Context(), p)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, wirejson.Object{
		{Key: "url", Value: "https://t.me/" + bot + "?start=link_" + code},
		{Key: "expires_in", Value: domain.LinkTTLSeconds},
	})
}

func (s *Server) listLinks(w http.ResponseWriter, r *http.Request) error {
	p, err := principal(r.Context())
	if err != nil {
		return err
	}
	links, err := s.svc.ListExternalIdentities(r.Context(), p)
	if err != nil {
		return err
	}
	out := make([]wirejson.Object, 0, len(links))
	for _, l := range links {
		out = append(out, linkOut(l))
	}
	return writeList(w, out)
}

func linkOut(l domain.ExternalIdentity) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: l.ID}, {Key: "provider", Value: l.Provider},
		{Key: "external_id", Value: l.ExternalID}, {Key: "linked_at", Value: naiveISO(l.CreatedAt)},
		{Key: "username", Value: strOrNil(l.Username)}, {Key: "display_name", Value: strOrNil(l.DisplayName)},
	}
}

// offerCode reads {code} after checking the caller may link a messenger account.
func offerCode(r *http.Request) (authn.Principal, string, error) {
	p, err := principal(r.Context())
	if err != nil {
		return p, "", err
	}
	if err := authn.EnsureScope(p, authn.ScopeCredentials, "link a messenger account"); err != nil {
		return p, "", err
	}
	var code string
	err = body(r, func(o wirejson.Object, errs *[]httpx.FieldError) { code = requiredStr(o, "code", errs) })
	return p, code, err
}

func (s *Server) previewTelegramOffer(w http.ResponseWriter, r *http.Request) error {
	p, code, err := offerCode(r)
	if err != nil {
		return err
	}
	v, err := s.svc.TelegramOffer(r.Context(), p, code)
	if err != nil {
		return err
	}
	o := v.Offer
	return writeJSON(w, http.StatusOK, wirejson.Object{
		{Key: "provider", Value: o.Provider}, {Key: "external_id", Value: o.ExternalID},
		{Key: "username", Value: emptyNil(o.Username)}, {Key: "display_name", Value: emptyNil(o.Name)},
		{Key: "bot", Value: emptyNil(o.Bot)}, {Key: "workspace_name", Value: v.WorkspaceName},
		{Key: "linked_to", Value: emptyNil(v.LinkedTo)},
	})
}

func (s *Server) acceptTelegramOffer(w http.ResponseWriter, r *http.Request) error {
	p, code, err := offerCode(r)
	if err != nil {
		return err
	}
	l, err := s.svc.AcceptTelegramOffer(r.Context(), p, code)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, linkOut(l))
}

func emptyNil(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func (s *Server) unlink(w http.ResponseWriter, r *http.Request) error {
	p, err := principal(r.Context())
	if err != nil {
		return err
	}
	if err := authn.EnsureScope(p, authn.ScopeCredentials, "unlink a messenger account"); err != nil {
		return err
	}
	id, err := pathUUID(r, "identity_id")
	if err != nil {
		return err
	}
	if err := s.svc.UnlinkExternalIdentity(r.Context(), p, id); err != nil {
		return err
	}
	return noContent(w)
}
