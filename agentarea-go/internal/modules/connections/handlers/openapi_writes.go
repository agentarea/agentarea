package handlers

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// oaBody adapts a body validator to the request middleware: errors are
// collected with the path's, the body is handed down unchanged.
func oaBody[T any](parse func(any, *[]httpx.FieldError) (T, bool)) func(any, *input, *[]httpx.FieldError) any {
	return func(v any, _ *input, errs *[]httpx.FieldError) any {
		parse(v, errs)
		return v
	}
}

// oaRead re-reads a body the middleware already validated.
func oaRead[T any](r *http.Request, parse func(any, *[]httpx.FieldError) (T, bool)) (T, wirejson.Object, error) {
	v, err := readBody(r)
	if err != nil {
		var zero T
		return zero, nil, err
	}
	var fes []httpx.FieldError
	out, _ := parse(v, &fes)
	if err := httpx.Validation(fes...); err != nil {
		return out, nil, err
	}
	o, _ := v.(wirejson.Object)
	return out, o, nil
}

func pathID(r *http.Request, name string) uuid.UUID { return uuid.MustParse(chi.URLParam(r, name)) }

func oaTools(tools []openapispec.Tool) []any {
	out := make([]any, 0, len(tools))
	for _, t := range tools {
		out = append(out, wirejson.Object{{Key: "name", Value: t.Name}, {Key: "description", Value: t.Description}})
	}
	return out
}

func policyRefused(err error) error {
	if errors.Is(err, governanceapi.ErrPolicyRefused) {
		return httpx.HTTPError(http.StatusUnprocessableEntity, err.Error()).Wrap(err)
	}
	return err
}

// discoverError is discover_tools' mapping: a refused spec is 400, any
// other failure a 500 that names no cause.
func discoverError(err error) error {
	var inv *domain.Invalid
	if errors.As(err, &inv) {
		return httpx.BadRequest(inv.Msg)
	}
	return httpx.HTTPError(http.StatusInternalServerError, "Failed to discover tools").Wrap(err)
}

func connectionCreated(w http.ResponseWriter, v service.ConnectionView) error {
	return response{status: http.StatusCreated, body: connectionJSON(v)}.visit(w)
}

func previewSpec(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	type preview struct {
		url  *string
		spec any
	}
	in, _, err := oaRead(r, func(v any, errs *[]httpx.FieldError) (preview, bool) {
		u, spec, ok := previewBody(v, errs)
		return preview{u, spec}, ok
	})
	if err != nil {
		return err
	}
	p, err := svc.PreviewSpec(r.Context(), in.url, in.spec)
	if err != nil {
		return err
	}
	return response{status: http.StatusOK, body: wirejson.Object{
		{Key: "title", Value: orNil(p.Info.Title)},
		{Key: "description", Value: orNil(p.Info.Description)},
		{Key: "base_url", Value: orNil(p.Info.BaseURL)},
		{Key: "version", Value: orNil(p.Info.Version)},
		{Key: "tools", Value: oaTools(p.Tools)},
	}}.visit(w)
}

func createConnection(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	in, _, err := oaRead(r, connectionCreateBody)
	if err != nil {
		return err
	}
	v, err := svc.CreateConnection(r.Context(), c, in, nil)
	if err != nil {
		return err
	}
	return connectionCreated(w, v)
}

func updateConnection(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	p, o, err := oaRead(r, connectionPatchBody)
	if err != nil {
		return err
	}
	if len(o) == 0 {
		return httpx.BadRequest("No fields to update")
	}
	v, err := svc.UpdateConnection(r.Context(), c, pathID(r, "connection_id"), p)
	if err != nil {
		return err
	}
	return response{status: http.StatusOK, body: connectionJSON(v)}.visit(w)
}

func setConnectionSharing(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	shared, _, err := oaRead(r, oaSharingBody)
	if err != nil {
		return err
	}
	v, err := svc.SetConnectionSharing(r.Context(), c, pathID(r, "connection_id"), shared)
	if err != nil {
		return err
	}
	return response{status: http.StatusOK, body: connectionJSON(v)}.visit(w)
}

func connectionToolPolicies(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	ps, err := svc.ConnectionToolPolicies(r.Context(), c, pathID(r, "connection_id"))
	if err != nil {
		return policyRefused(err)
	}
	return response{status: http.StatusOK, body: wirejson.Object{{Key: "tools", Value: instanceToolPoliciesJSON(ps)}}}.visit(w)
}

func discoverConnectionTools(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	d, err := svc.DiscoverTools(r.Context(), c, pathID(r, "connection_id"))
	if err != nil {
		return discoverError(err)
	}
	return response{status: http.StatusOK, body: wirejson.Object{
		{Key: "connection_id", Value: d.ConnectionID},
		{Key: "tools_discovered", Value: len(d.Tools)},
		{Key: "tools", Value: oaTools(d.Tools)},
	}}.visit(w)
}

func catalogError(err error) error {
	if errors.Is(err, service.ErrCatalogMisconfigured) {
		return httpx.HTTPError(http.StatusInternalServerError, "This catalog connection is misconfigured").Wrap(err)
	}
	return err
}

func catalogConnectForm(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	f, err := svc.CatalogConnectForm(r.Context(), c, pathID(r, "catalog_item_id"))
	if err != nil {
		return catalogError(err)
	}
	auth := "oauth"
	fields := []any{}
	if f.Template != nil {
		auth = "api_key"
		for _, k := range f.Template.Fields {
			fields = append(fields, wirejson.Object{{Key: "name", Value: k.Name}, {Key: "location", Value: k.Location},
				{Key: "label", Value: k.Label}, {Key: "description", Value: orNil(k.Description)}})
		}
	}
	return response{status: http.StatusOK, body: wirejson.Object{
		{Key: "catalog_item_id", Value: f.Item.ID.String()},
		{Key: "name", Value: f.Item.Name},
		{Key: "description", Value: orNil(f.Item.Description)},
		{Key: "auth", Value: auth},
		{Key: "fields", Value: fields},
	}}.visit(w)
}

func connectCatalogAPI(w http.ResponseWriter, r *http.Request, svc *service.Service) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	creds, _, err := oaRead(r, catalogConnectBody)
	if err != nil {
		return err
	}
	v, err := svc.ConnectCatalogAPI(r.Context(), c, pathID(r, "catalog_item_id"), creds)
	if err != nil {
		return catalogError(err)
	}
	return connectionCreated(w, v)
}
