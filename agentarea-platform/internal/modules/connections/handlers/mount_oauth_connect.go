package handlers

import (
	"context"
	"errors"
	"net/http"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// mountOAuthConnect is v1/oauth_connect.py: preflight and authorize in a
// workspace, the provider's callback with no session, the finish for the
// principal who started the flow.
func mountOAuthConnect(g group) {
	svc := g.s.svc
	if !svc.OAuthConnectReady() {
		return
	}
	p := httpx.WorkspacePrefix
	g.base.Method(http.MethodGet, p+"/oauth/preflight", g.errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		return oauthPreflight(w, r, svc)
	}))
	g.base.Method(http.MethodPost, p+"/oauth/authorize", g.errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		return oauthAuthorize(w, r, svc)
	}))
	g.r.Method(http.MethodGet, "/v1/oauth/callback", g.errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		q := r.URL.Query()
		loc, err := svc.OAuthReceive(r.Context(), q.Get("state"), q.Get("code"), q.Get("error"), q.Get("error_description"))
		if err != nil {
			return oauthHTTPError(err)
		}
		http.Redirect(w, r, loc, http.StatusFound)
		return nil
	}))
	if g.e.Authenticate == nil || g.e.Gate == nil {
		return
	}
	g.r.With(g.e.Authenticate).Method(http.MethodPost, "/v1/oauth/finish", g.errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		return oauthFinish(w, r, svc, g.e.Gate)
	}))
}

// oauthHTTPError renders the flow's refusals as Python raises them.
func oauthHTTPError(err error) error {
	var oe *service.OAuthError
	if !errors.As(err, &oe) {
		return err
	}
	if oe.Code == "" {
		return httpx.HTTPError(oe.Status, oe.Msg)
	}
	e := httpx.NewError(oe.Status, oe.Code, oe.Msg)
	if oe.WithIssuer {
		var issuer any
		if oe.Issuer != nil {
			issuer = *oe.Issuer
		}
		e = e.With("issuer", issuer)
	}
	return e
}

func writeOAuthJSON(w http.ResponseWriter, status int, body any) error {
	return response{status: status, body: body}.visit(w)
}

func oauthStrings(l []string) []any {
	out := make([]any, len(l))
	for i, s := range l {
		out[i] = s
	}
	return out
}

func preflightTargets() []string {
	return []string{"instance_id", "server_id", "catalog_item_id", "openapi_connection_id"}
}

func oauthPreflight(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	var fes []httpx.FieldError
	if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
		fes = append(fes, *fe)
	}
	ids := make([]*uuid.UUID, len(preflightTargets()))
	n := 0
	for i, name := range preflightTargets() {
		v, ok := last(r.URL.Query(), name)
		if !ok {
			continue
		}
		s, fe := httpx.ValidateUUID(v, "query", name)
		if fe != nil {
			fes = append(fes, *fe)
			continue
		}
		id := uuid.MustParse(s)
		ids[i] = &id
		n++
	}
	if err := httpx.Validation(fes...); err != nil {
		return err
	}
	if n != 1 {
		return httpx.HTTPError(http.StatusUnprocessableEntity, "Pass exactly one of instance_id, server_id, catalog_item_id or openapi_connection_id.")
	}
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	pf, err := svc.OAuthPreflight(r.Context(), c, service.OAuthTarget{
		InstanceID: ids[0], ServerID: ids[1], CatalogItemID: ids[2], OpenAPIConnectionID: ids[3],
	})
	if err != nil {
		return oauthHTTPError(err)
	}
	return writeOAuthJSON(w, http.StatusOK, wirejson.Object{
		{Key: "status", Value: pf.Status},
		{Key: "credential_source", Value: orNil(pf.CredentialSource)},
		{Key: "client_id", Value: orNil(pf.ClientID)},
		{Key: "connected", Value: pf.Connected},
		{Key: "detail", Value: pf.Detail},
		{Key: "issuer", Value: orNil(pf.Issuer)},
		{Key: "authorization_endpoint", Value: orNil(pf.AuthorizationEndpoint)},
		{Key: "scopes", Value: oauthStrings(pf.Scopes)},
		{Key: "default_scopes", Value: oauthStrings(pf.DefaultScopes)},
		{Key: "redirect_uri", Value: svc.OAuthCallbackURI()},
	})
}

func authorizeFields() []string {
	return []string{
		"client_id", "client_secret", "client_id_secret_id", "client_secret_secret_id",
		"instance_id", "catalog_item_id", "openapi_connection_id", "credential_mode", "scopes", "return_to",
	}
}

func oauthBoundedStr(o wirejson.Object, key string, minLen, maxLen int, errs *[]httpx.FieldError) *string {
	s, ok := optStr(o, key, errs)
	if !ok || s == nil {
		return nil
	}
	n := utf8.RuneCountInString(*s)
	if n < minLen {
		*errs = append(*errs, httpx.StringTooShort(minLen, "body", key))
		return nil
	}
	if n > maxLen {
		*errs = append(*errs, httpx.StringTooLong(maxLen, "body", key))
		return nil
	}
	return s
}

func oauthOptUUID(o wirejson.Object, key string, errs *[]httpx.FieldError) *uuid.UUID {
	s, ok := optStr(o, key, errs)
	if !ok || s == nil {
		return nil
	}
	id, fe := httpx.ValidateUUID(*s, "body", key)
	if fe != nil {
		*errs = append(*errs, *fe)
		return nil
	}
	u := uuid.MustParse(id)
	return &u
}

// authorizeBody is OAuthAuthorizeRequest (extra forbidden) and its model validator.
func authorizeBody(v any, errs *[]httpx.FieldError) service.AuthorizeRequest {
	var req service.AuthorizeRequest
	before := len(*errs)
	o, ok := model(v, errs)
	if !ok {
		return req
	}
	for _, m := range o {
		known := false
		for _, f := range authorizeFields() {
			known = known || f == m.Key
		}
		if !known {
			*errs = append(*errs, httpx.ExtraForbidden("body", m.Key))
		}
	}
	req.Custom.ClientID = oauthBoundedStr(o, "client_id", 1, 512, errs)
	req.Custom.ClientSecret = oauthBoundedStr(o, "client_secret", 1, 4096, errs)
	req.Custom.ClientIDSecretID = oauthOptUUID(o, "client_id_secret_id", errs)
	req.Custom.ClientSecretSecretID = oauthOptUUID(o, "client_secret_secret_id", errs)
	req.Target.InstanceID = oauthOptUUID(o, "instance_id", errs)
	req.Target.CatalogItemID = oauthOptUUID(o, "catalog_item_id", errs)
	req.Target.OpenAPIConnectionID = oauthOptUUID(o, "openapi_connection_id", errs)
	req.Mode = "auto"
	if mv, ok := o.Get("credential_mode"); ok {
		if s, isStr := mv.(string); isStr && (s == "auto" || s == "custom") {
			req.Mode = s
		} else {
			*errs = append(*errs, httpx.LiteralError([]string{"auto", "custom"}, "body", "credential_mode"))
		}
	}
	if sv, ok := o.Get("scopes"); ok && sv != nil {
		l, isList := sv.([]any)
		switch {
		case !isList:
			*errs = append(*errs, httpx.ListType("body", "scopes"))
		case len(l) == 0:
			*errs = append(*errs, httpx.FieldError{
				Type: "too_short", Loc: []any{"body", "scopes"},
				Msg: "List should have at least 1 item after validation, not 0",
				Ctx: wirejson.Object{{Key: "field_type", Value: "List"}, {Key: "min_length", Value: 1}, {Key: "actual_length", Value: 0}},
			})
		default:
			req.ScopesSet = true
			for i, x := range l {
				s, isStr := x.(string)
				if !isStr {
					*errs = append(*errs, httpx.StringType("body", "scopes", i))
					continue
				}
				req.Scopes = append(req.Scopes, s)
			}
		}
	}
	if rt, ok := o.Get("return_to"); ok {
		s, isStr := rt.(string)
		switch {
		case !isStr:
			*errs = append(*errs, httpx.StringType("body", "return_to"))
		case utf8.RuneCountInString(s) > 2048:
			*errs = append(*errs, httpx.StringTooLong(2048, "body", "return_to"))
		default:
			req.ReturnTo = s
		}
	}
	if len(*errs) > before {
		return req
	}
	targets := 0
	for _, t := range []*uuid.UUID{req.Target.InstanceID, req.Target.CatalogItemID, req.Target.OpenAPIConnectionID} {
		if t != nil {
			targets++
		}
	}
	custom := req.Custom
	switch {
	case targets != 1:
		*errs = append(*errs, httpx.ValueError("Pass exactly one of instance_id, catalog_item_id or openapi_connection_id.", "body"))
	case req.Mode == "auto":
		if custom.ClientID != nil || custom.ClientSecret != nil || custom.ClientIDSecretID != nil || custom.ClientSecretSecretID != nil {
			*errs = append(*errs, httpx.ValueError("Automatically chosen OAuth clients do not accept custom OAuth credentials.", "body"))
		}
	default:
		if (custom.ClientID == nil) == (custom.ClientIDSecretID == nil) {
			*errs = append(*errs, httpx.ValueError("Custom OAuth client ID must be entered or selected from workspace secrets.", "body"))
		} else if (custom.ClientSecret == nil) == (custom.ClientSecretSecretID == nil) {
			*errs = append(*errs, httpx.ValueError("Custom OAuth client secret must be entered or selected from workspace secrets.", "body"))
		}
	}
	return req
}

func oauthAuthorize(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	var fes []httpx.FieldError
	if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
		fes = append(fes, *fe)
	}
	v, err := readBody(r)
	if err != nil {
		return err
	}
	req := authorizeBody(v, &fes)
	if err := httpx.Validation(fes...); err != nil {
		return err
	}
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	loc, id, err := svc.OAuthAuthorize(r.Context(), c, req)
	if err != nil {
		return oauthHTTPError(err)
	}
	return writeOAuthJSON(w, http.StatusOK, wirejson.Object{
		{Key: "authorize_url", Value: loc},
		{Key: "connection_id", Value: id.String()},
	})
}

func oauthFinish(w http.ResponseWriter, r *http.Request, svc *service.Service, gate authn.Gate) error {
	var fes []httpx.FieldError
	v, err := readBody(r)
	if err != nil {
		return err
	}
	var token string
	if o, ok := model(v, &fes); ok {
		for _, m := range o {
			if m.Key != "token" {
				fes = append(fes, httpx.ExtraForbidden("body", m.Key))
			}
		}
		if s, ok := reqStr(o, "token", &fes); ok {
			switch n := utf8.RuneCountInString(s); {
			case n < 1:
				fes = append(fes, httpx.StringTooShort(1, "body", "token"))
			case n > 256:
				fes = append(fes, httpx.StringTooLong(256, "body", "token"))
			default:
				token = s
			}
		}
	}
	if err := httpx.Validation(fes...); err != nil {
		return err
	}
	p, ok := authn.PrincipalFrom(r.Context())
	if !ok {
		return authn.ErrUnauthenticated
	}
	loc, err := svc.OAuthFinish(r.Context(), p, token, func(ctx context.Context, workspaceID string) (authn.Caller, error) {
		return gate.EnterWorkspace(ctx, p, workspaceID)
	})
	if err != nil {
		return oauthHTTPError(err)
	}
	return writeOAuthJSON(w, http.StatusOK, wirejson.Object{{Key: "location", Value: loc}})
}
