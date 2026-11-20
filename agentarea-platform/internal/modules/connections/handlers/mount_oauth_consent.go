package handlers

import (
	"errors"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

const detailConsentNeedsSession = "Consent is given from a signed-in browser session"

// mountOAuthConsent is the consent decision for this API's authorization
// server: the web app's consent screen reads and decides it here, as the
// signed-in user (ADR-0058).
func mountOAuthConsent(g group) {
	if g.e.Authenticate == nil || g.e.Gate == nil || !g.s.svc.OAuthASReady() {
		return
	}
	svc, gate := g.s.svc, g.e.Gate
	r := g.r.With(g.e.Authenticate)
	r.Method(http.MethodGet, "/v1/oauth/consent", g.errs.Handler(func(w http.ResponseWriter, rq *http.Request) error {
		p, err := consentPrincipal(rq)
		if err != nil {
			return err
		}
		c, err := svc.Consent(rq.Context(), p.UserID, rq.URL.Query().Get("challenge"))
		if err != nil {
			return consentHTTPError(err)
		}
		return writeOAuthJSON(w, http.StatusOK, wirejson.Object{
			{Key: "client", Value: wirejson.Object{
				{Key: "client_id", Value: c.Client.ID},
				{Key: "client_name", Value: c.Client.Name},
				{Key: "client_uri", Value: c.Client.URI},
				{Key: "logo_uri", Value: c.Client.LogoURI},
				{Key: "redirect_uris", Value: oauthStrings(c.Client.RedirectURIs)},
			}},
			{Key: "redirect_uri", Value: c.RedirectURI},
			{Key: "first_party", Value: c.FirstParty},
			{Key: "access", Value: c.Access},
			{Key: "scopes", Value: oauthStrings(c.Scopes)},
		})
	}))
	r.Method(http.MethodPost, "/v1/oauth/consent", g.errs.Handler(func(w http.ResponseWriter, rq *http.Request) error {
		p, err := consentPrincipal(rq)
		if err != nil {
			return err
		}
		challenge, action, workspace, err := consentDecision(rq)
		if err != nil {
			return err
		}
		ctx := rq.Context()
		var to string
		if action == "reject" {
			to, err = svc.RejectConsent(ctx, p.UserID, challenge)
		} else {
			workspaceID := ""
			if workspace != "" {
				c, err := gate.EnterWorkspace(ctx, p, workspace)
				if err != nil {
					var unreachable *scope.UnreachableError
					if errors.As(err, &unreachable) {
						return httpx.Forbidden(authn.DetailNotAMember)
					}
					return err
				}
				workspaceID = c.Workspace.ID()
			}
			to, err = svc.AcceptConsent(ctx, p.UserID, challenge, workspaceID)
		}
		if err != nil {
			return consentHTTPError(err)
		}
		return writeOAuthJSON(w, http.StatusOK, wirejson.Object{{Key: "redirect_to", Value: to}})
	}))
}

// consentPrincipal is the signed-in user: an OAuth token or a key never
// consents for a client.
func consentPrincipal(r *http.Request) (authn.Principal, error) {
	p, ok := authn.PrincipalFrom(r.Context())
	if !ok {
		return authn.Principal{}, authn.ErrUnauthenticated
	}
	if p.Credential == nil || p.Credential.Kind != authn.KindSession {
		return authn.Principal{}, httpx.Forbidden(detailConsentNeedsSession)
	}
	return p, nil
}

func consentDecision(r *http.Request) (challenge, action, workspace string, err error) {
	var fes []httpx.FieldError
	v, err := readBody(r)
	if err != nil {
		return "", "", "", err
	}
	if o, ok := model(v, &fes); ok {
		for _, m := range o {
			switch m.Key {
			case "challenge", "action", "workspace":
			default:
				fes = append(fes, httpx.ExtraForbidden("body", m.Key))
			}
		}
		challenge, _ = reqStr(o, "challenge", &fes)
		if a, ok := reqStr(o, "action", &fes); ok {
			if a != "accept" && a != "reject" {
				fes = append(fes, httpx.LiteralError([]string{"accept", "reject"}, "body", "action"))
			}
			action = a
		}
		if ws, ok := optStr(o, "workspace", &fes); ok && ws != nil {
			workspace = *ws
		}
	}
	if err := httpx.Validation(fes...); err != nil {
		return "", "", "", err
	}
	return challenge, action, workspace, nil
}

func consentHTTPError(err error) error {
	switch {
	case errors.Is(err, service.ErrConsentNotFound):
		return httpx.NotFound("Consent request not found or expired")
	case errors.Is(err, service.ErrConsentNotYours):
		return httpx.Forbidden("Consent request does not belong to this session")
	case errors.Is(err, service.ErrConsentNeedsWorkspace):
		return httpx.Validation(httpx.Missing("body", "workspace"))
	}
	return httpx.HTTPError(http.StatusBadGateway, "Authorization server unavailable").Wrap(err)
}
