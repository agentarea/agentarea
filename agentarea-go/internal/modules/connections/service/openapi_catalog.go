package service

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
)

// ErrCatalogMisconfigured is a catalog item whose key template does not
// parse ("This catalog connection is misconfigured", a 500).
var ErrCatalogMisconfigured = errors.New("catalog connection is misconfigured")

// CatalogForm is CatalogConnectFormResponse: Template nil connects by signing in.
type CatalogForm struct {
	Item     CatalogAPIItem
	Template *openapispec.KeyTemplate
}

func (s *Service) catalogKeyItem(ctx context.Context, c authn.Caller, id uuid.UUID) (CatalogForm, error) {
	if s.d.CatalogItems == nil {
		return CatalogForm{}, &domain.Unavailable{Msg: "Catalog API connections are not available"}
	}
	item, err := s.d.CatalogItems.CatalogAPIItem(ctx, c.Workspace, id)
	if err != nil {
		return CatalogForm{}, err
	}
	t, err := openapispec.CatalogKeyTemplate(item.Spec)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Catalog item has a malformed key template", "catalog_item_id", id, "error", err)
		return CatalogForm{}, ErrCatalogMisconfigured
	}
	return CatalogForm{Item: item, Template: t}, nil
}

// CatalogConnectForm is get_catalog_connect_form.
func (s *Service) CatalogConnectForm(ctx context.Context, c authn.Caller, id uuid.UUID) (CatalogForm, error) {
	return s.catalogKeyItem(ctx, c, id)
}

// ConnectCatalogAPI is connect_catalog_api: a new connection from the
// catalog item, its keys stored as secret headers and query parameters.
// credentials are (name, value) in body order.
func (s *Service) ConnectCatalogAPI(ctx context.Context, c authn.Caller, id uuid.UUID, credentials [][2]string) (ConnectionView, error) {
	form, err := s.catalogKeyItem(ctx, c, id)
	if err != nil {
		return ConnectionView{}, err
	}
	if form.Template == nil {
		return ConnectionView{}, &domain.Invalid{Msg: "This catalog API connects by signing in"}
	}
	values := map[string]string{}
	for _, kv := range credentials {
		values[kv[0]] = kv[1]
	}
	if len(values) != len(credentials) {
		return ConnectionView{}, &domain.Invalid{Msg: "A field was given twice"}
	}
	headers, query, err := form.Template.Credentials(values)
	if err != nil {
		return ConnectionView{}, invalid(err)
	}
	spec := form.Item.Spec
	in := ConnectionCreate{Name: form.Item.Name, Description: form.Item.Description}
	if openapispec.Truthy(spec["base_url"]) {
		in.BaseURL = oaPyStr(spec["base_url"])
	}
	if u, ok := spec["spec_url"].(string); ok {
		in.SpecURL = &u
	}
	if content, ok := spec["spec_content"].(map[string]any); ok {
		in.SpecContent = content
	}
	for _, h := range headers {
		in.Headers = append(in.Headers, HeaderIn{Name: h.Name, Value: h.Value})
	}
	for _, q := range query {
		in.Query = append(in.Query, QueryIn{Name: q.Name, Secret: true, Value: q.Value})
	}
	itemID := form.Item.ID
	return s.CreateConnection(ctx, c, in, &itemID)
}
