package handlers

import (
	"encoding/json"
	"net/http"
	"strings"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// mountOAuthInstallations lists the GitHub App installations a connection
// signed in through a platform GitHub App can be bound to, and binds it.
func mountOAuthInstallations(g group) {
	svc := g.s.svc
	p := httpx.WorkspacePrefix
	g.base.Method(http.MethodGet, p+"/oauth/installations", g.errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		ref, err := installationQuery(r)
		if err != nil {
			return err
		}
		c, err := caller(r.Context())
		if err != nil {
			return err
		}
		list, err := svc.OAuthInstallations(r.Context(), c, ref)
		if err != nil {
			return oauthHTTPError(err)
		}
		out := make([]any, len(list))
		for i, in := range list {
			out[i] = wirejson.Object{
				{Key: "id", Value: in.ID},
				{Key: "account", Value: in.Account},
				{Key: "account_type", Value: in.AccountType},
				{Key: "repository_selection", Value: in.RepositorySelection},
			}
		}
		return writeOAuthJSON(w, http.StatusOK, wirejson.Object{{Key: "installations", Value: out}})
	}))
	g.base.Method(http.MethodGet, p+"/oauth/installations/{installation_id}/repositories", g.errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		id, fe := httpx.ValidateInt(chi.URLParam(r, "installation_id"), httpx.IntBounds{Ge: 1, HasGe: true}, "path", "installation_id")
		ref, err := installationQuery(r)
		if fe != nil {
			return httpx.Validation(*fe)
		}
		if err != nil {
			return err
		}
		c, err := caller(r.Context())
		if err != nil {
			return err
		}
		list, err := svc.OAuthInstallationRepositories(r.Context(), c, ref, id)
		if err != nil {
			return oauthHTTPError(err)
		}
		out := make([]any, len(list))
		for i, repo := range list {
			out[i] = wirejson.Object{
				{Key: "name", Value: repo.Name},
				{Key: "full_name", Value: repo.FullName},
				{Key: "private", Value: repo.Private},
			}
		}
		return writeOAuthJSON(w, http.StatusOK, wirejson.Object{{Key: "repositories", Value: out}})
	}))
	g.base.Method(http.MethodPut, p+"/oauth/installation", g.errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		var fes []httpx.FieldError
		if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
			fes = append(fes, *fe)
		}
		v, err := readBody(r)
		if err != nil {
			return err
		}
		ref, req := installationBindingBody(v, &fes)
		if err := httpx.Validation(fes...); err != nil {
			return err
		}
		c, err := caller(r.Context())
		if err != nil {
			return err
		}
		b, err := svc.BindOAuthInstallation(r.Context(), c, ref, req)
		if err != nil {
			return oauthHTTPError(err)
		}
		return writeOAuthJSON(w, http.StatusOK, wirejson.Object{{Key: "installation_binding", Value: installationBindingJSON(b)}})
	}))
}

func installationBindingJSON(b *service.InstallationBinding) any {
	if b == nil {
		return nil
	}
	var repos any
	if b.Repositories != nil {
		repos = oauthStrings(b.Repositories)
	}
	return wirejson.Object{
		{Key: "installation_id", Value: b.InstallationID},
		{Key: "account", Value: b.Account},
		{Key: "repositories", Value: repos},
	}
}

// installationQuery is the one connection, instance_id or openapi_connection_id, a listing acts on.
func installationQuery(r *http.Request) (service.OAuthTarget, error) {
	var fes []httpx.FieldError
	if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
		fes = append(fes, *fe)
	}
	var ref service.OAuthTarget
	n := 0
	for _, name := range []string{"instance_id", "openapi_connection_id"} {
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
		if name == "instance_id" {
			ref.InstanceID = &id
		} else {
			ref.OpenAPIConnectionID = &id
		}
		n++
	}
	if err := httpx.Validation(fes...); err != nil {
		return ref, err
	}
	if n != 1 {
		return ref, httpx.HTTPError(http.StatusUnprocessableEntity, "Pass exactly one of instance_id or openapi_connection_id.")
	}
	return ref, nil
}

// installationBindingBody is OAuthInstallationBindingRequest (extra
// forbidden): a null installation_id clears the binding.
func installationBindingBody(v any, errs *[]httpx.FieldError) (service.OAuthTarget, *service.InstallationBindingRequest) {
	var ref service.OAuthTarget
	o, ok := model(v, errs)
	if !ok {
		return ref, nil
	}
	for _, m := range o {
		switch m.Key {
		case "instance_id", "openapi_connection_id", "installation_id", "repositories":
		default:
			*errs = append(*errs, httpx.ExtraForbidden("body", m.Key))
		}
	}
	before := len(*errs)
	ref.InstanceID = oauthOptUUID(o, "instance_id", errs)
	ref.OpenAPIConnectionID = oauthOptUUID(o, "openapi_connection_id", errs)
	var req *service.InstallationBindingRequest
	iv, ok := o.Get("installation_id")
	switch {
	case !ok:
		*errs = append(*errs, httpx.Missing("body", "installation_id"))
	case iv == nil:
	default:
		num, isNum := iv.(json.Number)
		id, err := num.Int64()
		_, isFloat := iv.(wirejson.Float)
		switch {
		case isFloat:
			*errs = append(*errs, httpx.IntFromFloat("body", "installation_id"))
		case !isNum || err != nil:
			*errs = append(*errs, httpx.IntType("body", "installation_id"))
		case id < 1:
			*errs = append(*errs, httpx.GreaterThanEqual(1, "body", "installation_id"))
		default:
			req = &service.InstallationBindingRequest{InstallationID: id}
		}
	}
	if rv, ok := o.Get("repositories"); ok && rv != nil {
		l, isList := rv.([]any)
		if !isList {
			*errs = append(*errs, httpx.ListType("body", "repositories"))
		}
		for i, x := range l {
			s, isStr := x.(string)
			switch {
			case !isStr:
				*errs = append(*errs, httpx.StringType("body", "repositories", i))
			case strings.TrimSpace(s) == "" || utf8.RuneCountInString(s) > 100:
				*errs = append(*errs, httpx.ValueError("A repository is named by its name, 1 to 100 characters.", "body", "repositories", i))
			case req != nil:
				req.Repositories = append(req.Repositories, s)
			}
		}
		if req == nil && len(l) > 0 && len(*errs) == before {
			*errs = append(*errs, httpx.ValueError("Repositories need an installation_id.", "body"))
		}
	}
	if len(*errs) == before && (ref.InstanceID == nil) == (ref.OpenAPIConnectionID == nil) {
		*errs = append(*errs, httpx.ValueError("Pass exactly one of instance_id or openapi_connection_id.", "body"))
	}
	return ref, req
}
