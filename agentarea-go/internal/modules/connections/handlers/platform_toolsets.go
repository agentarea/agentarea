package handlers

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// toolRefusal is the text a tool refusal carries: require_permission's detail.
func toolRefusal(err error) error {
	if errors.Is(err, authz.ErrDenied) {
		return errors.New("Permission denied") //nolint:staticcheck // Python's detail
	}
	return err
}

// requireOn is the tool layer's requires(action, resource, id_param): the
// argument must be a UUID, and the caller must hold action on it.
func requireOn(ctx context.Context, svc *service.Service, c authn.Caller, action, resourceType, param, raw string) (uuid.UUID, error) {
	id, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, errors.New(param + " must be a UUID")
	}
	if err := svc.Require(ctx, c, action, resourceType, id.String()); err != nil {
		return uuid.Nil, toolRefusal(err)
	}
	return id, nil
}

// toolDocument decodes a tool's document as a request body is decoded.
func toolDocument(doc json.RawMessage) (wirejson.Object, error) {
	v, err := wirejson.Unmarshal(doc)
	if err != nil {
		return nil, err
	}
	o, ok := v.(wirejson.Object)
	if !ok {
		return nil, errors.New("the document is not an object")
	}
	return o, nil
}

// checked runs a REST body's validation over o.
func checked[T any](o wirejson.Object, parse func(any, *[]httpx.FieldError) (T, bool)) (T, error) {
	var fes []httpx.FieldError
	out, _ := parse(o, &fes)
	return out, httpx.Validation(fes...)
}

// checkedInput runs a REST body's input validation over o.
func checkedInput(o wirejson.Object, parse func(any, *input, *[]httpx.FieldError) any) (input, error) {
	var in input
	var fes []httpx.FieldError
	parse(o, &in, &fes)
	return in, httpx.Validation(fes...)
}

func notFoundAs(err, as error) error {
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		return as
	}
	return err
}

// OpenAPIToolset is api.PlatformOpenAPI over the connections service.
type OpenAPIToolset struct{ Svc *service.Service }

var _ api.PlatformOpenAPI = OpenAPIToolset{}

func namedFields[T domain.Header | domain.QueryParam](items []T) []api.NamedField {
	out := make([]api.NamedField, 0, len(items))
	for _, it := range items {
		switch v := any(it).(type) {
		case domain.Header:
			out = append(out, api.NamedField{Name: v.Name, Secret: v.Secret})
		case domain.QueryParam:
			out = append(out, api.NamedField{Name: v.Name, Secret: v.Secret})
		}
	}
	return out
}

func openAPIOut(conn domain.Connection) api.OpenAPIConnection {
	tools := make([]api.OpenAPITool, 0, len(conn.AvailableTools))
	for _, t := range conn.AvailableTools {
		tools = append(tools, api.OpenAPITool{Name: t.Name, Description: t.Description})
	}
	vars := conn.URLVariables
	if vars == nil {
		vars = []string{}
	}
	return api.OpenAPIConnection{
		ID: conn.ID, Name: conn.Name, Description: conn.Description, BaseURL: conn.VisibleBaseURL(),
		SpecURL: conn.SpecURL, AuthConfigID: conn.AuthConfigID,
		CustomHeaders: namedFields(conn.CustomHeaders), CustomQueryParams: namedFields(conn.CustomQuery),
		URLVariables: vars, Tools: tools, Status: conn.Status, LastDispatch: conn.LastDispatch,
	}
}

func (t OpenAPIToolset) Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.OpenAPIConnection, error) {
	o, err := toolDocument(doc)
	if err != nil {
		return api.OpenAPIConnection{}, err
	}
	in, err := checked(o, connectionCreateBody)
	if err != nil {
		return api.OpenAPIConnection{}, err
	}
	v, err := t.Svc.CreateConnection(ctx, c, in, nil)
	if err != nil {
		return api.OpenAPIConnection{}, err
	}
	return openAPIOut(v.Connection), nil
}

func (t OpenAPIToolset) List(ctx context.Context, c authn.Caller, search string, limit, offset int) ([]api.OpenAPIConnection, int, error) {
	vs, total, err := t.Svc.ConnectionsPage(ctx, c, search, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	out := make([]api.OpenAPIConnection, len(vs))
	for i, v := range vs {
		out[i] = openAPIOut(v.Connection)
	}
	return out, total, nil
}

func (t OpenAPIToolset) Get(ctx context.Context, c authn.Caller, connectionID string) (api.OpenAPIConnection, error) {
	id, err := uuid.Parse(connectionID)
	if err != nil {
		return api.OpenAPIConnection{}, err
	}
	v, err := t.Svc.GetConnection(ctx, c, id)
	if err != nil {
		return api.OpenAPIConnection{}, notFoundAs(err, api.ErrNotFound)
	}
	return openAPIOut(v.Connection), nil
}

func (t OpenAPIToolset) Update(ctx context.Context, c authn.Caller, connectionID string, doc json.RawMessage) (api.OpenAPIConnection, error) {
	id, err := requireOn(ctx, t.Svc, c, "edit", "openapi_connection", "connection_id", connectionID)
	if err != nil {
		return api.OpenAPIConnection{}, err
	}
	o, err := toolDocument(doc)
	if err != nil {
		return api.OpenAPIConnection{}, err
	}
	if len(o) == 0 {
		return api.OpenAPIConnection{}, errors.New("no fields to update")
	}
	p, err := checked(o, connectionPatchBody)
	if err != nil {
		return api.OpenAPIConnection{}, err
	}
	v, err := t.Svc.UpdateConnection(ctx, c, id, p)
	if err != nil {
		return api.OpenAPIConnection{}, notFoundAs(err, api.ErrNotFound)
	}
	return openAPIOut(v.Connection), nil
}

func (t OpenAPIToolset) DiscoverTools(ctx context.Context, c authn.Caller, connectionID string) (api.OpenAPIDiscovery, error) {
	id, err := requireOn(ctx, t.Svc, c, "edit", "openapi_connection", "connection_id", connectionID)
	if err != nil {
		return api.OpenAPIDiscovery{}, err
	}
	d, err := t.Svc.DiscoverTools(ctx, c, id)
	if err != nil {
		return api.OpenAPIDiscovery{}, err
	}
	tools := make([]api.OpenAPITool, len(d.Tools))
	for i, tool := range d.Tools {
		tools[i] = api.OpenAPITool{Name: tool.Name, Description: tool.Description}
	}
	return api.OpenAPIDiscovery{ConnectionID: d.ConnectionID, Tools: tools}, nil
}

func (t OpenAPIToolset) Delete(ctx context.Context, c authn.Caller, connectionID string) (bool, error) {
	id, err := requireOn(ctx, t.Svc, c, "delete", "openapi_connection", "connection_id", connectionID)
	if err != nil {
		return false, err
	}
	err = t.Svc.DeleteConnection(ctx, c, id)
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		return false, nil
	}
	return err == nil, err
}
