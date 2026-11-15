package handlers

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"slices"
	"strconv"
	"time"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/catalog"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
)

// Server implements the catalog routes (api/v1/registries.py,
// workspace_registries.py).
type Server struct {
	svc         *service.Service
	connections service.CatalogConnections
	pricing     service.CatalogPricing
	admin       func(context.Context) error
	rate        httpx.RateLimiter
	log         *slog.Logger
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server; connections and pricing may be nil, which leaves
// the routes that render a connection's card unmounted.
func New(svc *service.Service, connections service.CatalogConnections, pricing service.CatalogPricing, admin func(context.Context) error) *Server {
	return &Server{svc: svc, connections: connections, pricing: pricing, admin: admin}
}

// WithRateLimit is the limiter the workspace-registry sync takes its token
// from; without it that route stays unmounted.
func (s *Server) WithRateLimit(rl httpx.RateLimiter, log *slog.Logger) *Server {
	s.rate, s.log = rl, log
	return s
}

func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// MapError renders the module's errors as the routes raise them.
func MapError(err error) (*httpx.Error, bool) {
	var ve *service.ValueError
	var nf *service.NotFoundError
	var ce *service.ConflictError
	var fe *service.ForbiddenError
	switch {
	case errors.As(err, &fe):
		return httpx.HTTPError(http.StatusForbidden, fe.Detail), true
	case errors.As(err, &nf):
		return httpx.HTTPError(http.StatusNotFound, nf.Detail), true
	case errors.As(err, &ce):
		return httpx.HTTPError(http.StatusConflict, ce.Detail), true
	case errors.As(err, &ve):
		return httpx.HTTPError(http.StatusBadRequest, ve.Msg), true
	}
	return nil, false
}

func utcISO(t time.Time) string {
	s := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += fmt.Sprintf(".%06d", us)
	}
	return s + "Z"
}

func utcISOPtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return utcISO(*t)
}

func orNil[T any](p *T) any {
	if p == nil {
		return nil
	}
	return *p
}

// registryJSON is RegistryResponse in its field order.
func registryJSON(r domain.Registry) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: r.ID},
		{Key: "name", Value: r.Name},
		{Key: "description", Value: orNil(r.Description)},
		{Key: "registry_type", Value: r.RegistryType},
		{Key: "source_type", Value: r.SourceType},
		{Key: "source_url", Value: r.SourceURL},
		{Key: "source_ref", Value: orNil(r.SourceRef)},
		{Key: "source_path", Value: orNil(r.SourcePath)},
		{Key: "is_active", Value: r.IsActive},
		{Key: "scope", Value: r.Scope},
		{Key: "workspace_id", Value: orNil(r.WorkspaceID)},
		{Key: "mode", Value: r.Mode},
		{Key: "trust", Value: r.Trust},
		{Key: "credentials_secret_id", Value: orNil(r.CredentialsSecretRef)},
		{Key: "last_synced_at", Value: utcISOPtr(r.LastSyncedAt)},
		{Key: "last_sync_error", Value: orNil(r.LastSyncError)},
		{Key: "item_count", Value: r.ItemCount},
		{Key: "recommendation_priority", Value: r.RecommendationPriority},
		{Key: "created_at", Value: utcISO(r.CreatedAt)},
		{Key: "updated_at", Value: utcISO(r.UpdatedAt)},
	}
}

// decoded is a stored JSON column as Python reads it back, or fallback for
// an empty one (`item.spec or {}`).
func decoded(raw []byte, fallback any) any {
	v, err := wirejson.Unmarshal(raw)
	if err != nil || v == nil {
		return fallback
	}
	switch t := v.(type) {
	case wirejson.Object:
		if len(t) == 0 {
			return fallback
		}
	case []any:
		if len(t) == 0 {
			return fallback
		}
	}
	return v
}

// card is what a card adds to an item: its connections, pricing and source.
type card struct {
	connections any
	pricing     any
	registry    *domain.Registry
}

// itemJSON is RegistryItemResponse in its field order.
func itemJSON(i domain.Item, c card) wirejson.Object {
	var name, scope, mode any
	if c.registry != nil {
		name, scope, mode = c.registry.Name, c.registry.Scope, c.registry.Mode
	}
	return wirejson.Object{
		{Key: "id", Value: i.ID},
		{Key: "registry_id", Value: i.RegistryID},
		{Key: "external_id", Value: i.ExternalID},
		{Key: "name", Value: i.Name},
		{Key: "description", Value: orNil(i.Description)},
		{Key: "version", Value: orNil(i.Version)},
		{Key: "spec", Value: decoded(i.Spec, wirejson.Object{})},
		{Key: "tags", Value: decoded(i.Tags, []any{})},
		{Key: "installed_entity_id", Value: orNil(i.InstalledEntityID)},
		{Key: "update_available", Value: i.UpdateAvailable},
		{Key: "installed_version", Value: orNil(i.InstalledVersion)},
		{Key: "category", Value: orNil(i.Category)},
		{Key: "featured", Value: i.Featured},
		{Key: "hosting", Value: orNil(i.Hosting)},
		{Key: "workspace_connections", Value: c.connections},
		{Key: "pricing", Value: c.pricing},
		{Key: "registry_name", Value: name},
		{Key: "registry_scope", Value: scope},
		{Key: "registry_mode", Value: mode},
		{Key: "registry_trust", Value: i.RegistryTrust},
		{Key: "created_at", Value: utcISO(i.CreatedAt)},
		{Key: "updated_at", Value: utcISO(i.UpdatedAt)},
	}
}

func source(m map[string]domain.Registry, id string) *domain.Registry {
	if r, ok := m[id]; ok {
		return &r
	}
	return nil
}

// response is a JSONResponse body as Starlette writes it, or an empty 204.
type response struct {
	status int
	body   any
}

func (x response) visit(w http.ResponseWriter) error {
	if x.status == http.StatusNoContent {
		w.WriteHeader(x.status)
		return nil
	}
	raw, err := wirejson.Marshal(x.body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

func ok(body any) response { return response{status: http.StatusOK, body: body} }

func registries(rs []domain.Registry) []any {
	out := make([]any, len(rs))
	for i, r := range rs {
		out[i] = registryJSON(r)
	}
	return out
}

func (s *Server) ListRegistriesV1RegistriesGet(ctx context.Context, _ gen.ListRegistriesV1RegistriesGetRequestObject) (gen.ListRegistriesV1RegistriesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	rs, err := s.svc.ListRegistries(ctx, c.Workspace, in.activeOnly, in.registryType, in.scope)
	if err != nil {
		return nil, err
	}
	return ok(registries(rs)), nil
}

func (s *Server) CreateRegistryV1RegistriesPost(ctx context.Context, _ gen.CreateRegistryV1RegistriesPostRequestObject) (gen.CreateRegistryV1RegistriesPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	r, err := s.svc.CreateRegistry(ctx, c.Workspace, in.registry, in.priority)
	if err != nil {
		return nil, err
	}
	return ok(registryJSON(r)), nil
}

func (s *Server) GetRegistryV1RegistriesRegistryIdGet(ctx context.Context, rq gen.GetRegistryV1RegistriesRegistryIdGetRequestObject) (gen.GetRegistryV1RegistriesRegistryIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	r, found, err := s.svc.VisibleRegistry(ctx, c.Workspace, rq.RegistryId.String())
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, service.ErrRegistryNotFound()
	}
	return ok(registryJSON(r)), nil
}

func (s *Server) UpdateRegistryV1RegistriesRegistryIdPatch(ctx context.Context, rq gen.UpdateRegistryV1RegistriesRegistryIdPatchRequestObject) (gen.UpdateRegistryV1RegistriesRegistryIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	p := inputFrom(ctx).registryPatch
	if p.Empty() {
		return nil, service.ErrNoFields()
	}
	current, found, err := s.svc.PlatformRegistry(ctx, c.Workspace, rq.RegistryId.String())
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, service.ErrRegistryNotFound()
	}
	r, err := s.svc.UpdateRegistry(ctx, c.Workspace, current, p)
	if err != nil {
		return nil, err
	}
	return ok(registryJSON(r)), nil
}

func (s *Server) DeleteRegistryV1RegistriesRegistryIdDelete(ctx context.Context, rq gen.DeleteRegistryV1RegistriesRegistryIdDeleteRequestObject) (gen.DeleteRegistryV1RegistriesRegistryIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	id := rq.RegistryId.String()
	if _, found, err := s.svc.PlatformRegistry(ctx, c.Workspace, id); err != nil {
		return nil, err
	} else if !found {
		return nil, service.ErrRegistryNotFound()
	}
	deleted, err := s.svc.DeleteRegistry(ctx, c.Workspace, id)
	if err != nil {
		return nil, err
	}
	if !deleted {
		return nil, service.ErrRegistryNotFound()
	}
	return ok(wirejson.Object{{Key: "status", Value: "deleted"}}), nil
}

func (s *Server) ListRegistryItemsV1RegistriesRegistryIdItemsGet(ctx context.Context, rq gen.ListRegistryItemsV1RegistriesRegistryIdItemsGetRequestObject) (gen.ListRegistryItemsV1RegistriesRegistryIdItemsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	r, found, err := s.svc.VisibleRegistry(ctx, c.Workspace, rq.RegistryId.String())
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, service.ErrRegistryNotFound()
	}
	items, err := s.svc.ListItems(ctx, c.Workspace, r.ID, in.limit, in.offset)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(items))
	for i, it := range items {
		out[i] = itemJSON(it, card{registry: &r})
	}
	return ok(out), nil
}

func (s *Server) CreateCatalogItemV1RegistriesRegistryIdItemsPost(ctx context.Context, rq gen.CreateCatalogItemV1RegistriesRegistryIdItemsPostRequestObject) (gen.CreateCatalogItemV1RegistriesRegistryIdItemsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	it, err := s.svc.CreateCatalogItem(ctx, c.Workspace, rq.RegistryId.String(), inputFrom(ctx).item)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: itemJSON(it, card{})}, nil
}

func (s *Server) UpdateCatalogItemV1RegistriesCatalogItemsItemIdPatch(ctx context.Context, rq gen.UpdateCatalogItemV1RegistriesCatalogItemsItemIdPatchRequestObject) (gen.UpdateCatalogItemV1RegistriesCatalogItemsItemIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	p := inputFrom(ctx).itemPatch
	if p.Empty() {
		return nil, service.ErrNoFields()
	}
	it, err := s.svc.UpdateCatalogItem(ctx, c.Workspace, rq.ItemId.String(), p)
	if err != nil {
		return nil, err
	}
	return ok(itemJSON(it, card{})), nil
}

func (s *Server) DeleteCatalogItemV1RegistriesCatalogItemsItemIdDelete(ctx context.Context, rq gen.DeleteCatalogItemV1RegistriesCatalogItemsItemIdDeleteRequestObject) (gen.DeleteCatalogItemV1RegistriesCatalogItemsItemIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteCatalogItem(ctx, c.Workspace, rq.ItemId.String()); err != nil {
		return nil, err
	}
	return response{status: http.StatusNoContent}, nil
}

func (s *Server) SearchCatalogV1RegistriesCatalogSearchGet(ctx context.Context, _ gen.SearchCatalogV1RegistriesCatalogSearchGetRequestObject) (gen.SearchCatalogV1RegistriesCatalogSearchGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	items, err := s.svc.Search(ctx, c.Workspace, in.q, in.tag, in.updateAvailable, in.limit, in.offset)
	if err != nil {
		return nil, err
	}
	sources, err := s.svc.RegistriesOf(ctx, c.Workspace, items)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(items))
	for i, it := range items {
		out[i] = itemJSON(it, card{registry: source(sources, it.RegistryID)})
	}
	return ok(out), nil
}

func facets(fs []domain.Facet) []any {
	out := make([]any, len(fs))
	for i, f := range fs {
		out[i] = wirejson.Object{{Key: "value", Value: f.Value}, {Key: "count", Value: f.Count}}
	}
	return out
}

func (s *Server) BrowseCatalogV1RegistriesCatalogBrowseGet(ctx context.Context, _ gen.BrowseCatalogV1RegistriesCatalogBrowseGetRequestObject) (gen.BrowseCatalogV1RegistriesCatalogBrowseGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	f := in.browse
	if !slices.Contains(domain.RegistryTypes(), f.RegistryType) {
		return nil, &service.ValueError{Msg: "registry_type must be one of " + service.PyTuple(domain.RegistryTypes()...)}
	}
	sort := "recommended"
	if in.sort != nil {
		if *in.sort != "recommended" && *in.sort != "name" {
			return nil, &service.ValueError{Msg: "sort must be one of " + service.PyTuple("recommended", "name")}
		}
		sort = *in.sort
	}
	for _, dim := range []struct {
		name string
		set  bool
	}{{"protocol", in.protocolSet}, {"hosting", in.hostingSet}, {"pricing", in.pricingSet}} {
		if dim.set && f.RegistryType != domain.TypeMCPServers {
			return nil, &service.ValueError{Msg: fmt.Sprintf("%s only applies to registry_type='%s'", dim.name, domain.TypeMCPServers)}
		}
	}
	b, err := s.svc.Browse(ctx, c.Workspace, f, sort, in.limit, in.offset)
	if err != nil {
		return nil, err
	}
	var found map[string][]any
	if f.RegistryType == domain.TypeMCPServers && len(b.Items) > 0 {
		ids := make([]string, len(b.Items))
		for i, it := range b.Items {
			ids[i] = it.ID
		}
		if found, err = s.connections.Of(ctx, c, ids); err != nil {
			return nil, err
		}
	}
	prices, err := s.pricing.Price(ctx, b.Items)
	if err != nil {
		return nil, err
	}
	sources, err := s.svc.RegistriesOf(ctx, c.Workspace, b.Items)
	if err != nil {
		return nil, err
	}
	items := make([]any, len(b.Items))
	for i, it := range b.Items {
		cd := card{pricing: prices[i], registry: source(sources, it.RegistryID)}
		if found != nil {
			conns := found[it.ID]
			if conns == nil {
				conns = []any{}
			}
			cd.connections = conns
		}
		items[i] = itemJSON(it, cd)
	}
	return ok(wirejson.Object{
		{Key: "items", Value: items},
		{Key: "total", Value: b.Total},
		{Key: "categories", Value: facets(b.Categories)},
		{Key: "protocols", Value: facets(b.Protocols)},
		{Key: "hostings", Value: facets(b.Hostings)},
		{Key: "pricings", Value: facets(b.Pricing)},
	}), nil
}

func (s *Server) GetCatalogItemV1RegistriesCatalogItemsItemIdGet(ctx context.Context, rq gen.GetCatalogItemV1RegistriesCatalogItemsItemIdGetRequestObject) (gen.GetCatalogItemV1RegistriesCatalogItemsItemIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	it, found, err := s.svc.VisibleItem(ctx, c.Workspace, rq.ItemId.String())
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, service.ErrItemNotFound()
	}
	r, visible, err := s.svc.VisibleRegistry(ctx, c.Workspace, it.RegistryID)
	if err != nil {
		return nil, err
	}
	cd := card{}
	if visible {
		cd.registry = &r
	}
	if it.RegistryType != domain.TypeMCPServers {
		return ok(itemJSON(it, cd)), nil
	}
	conns, err := s.connections.Of(ctx, c, []string{it.ID})
	if err != nil {
		return nil, err
	}
	cd.connections = conns[it.ID]
	if cd.connections == nil {
		cd.connections = []any{}
	}
	prices, err := s.pricing.Price(ctx, []domain.Item{it})
	if err != nil {
		return nil, err
	}
	cd.pricing = prices[0]
	return ok(itemJSON(it, cd)), nil
}

func (s *Server) ListWorkspaceRegistriesV1WorkspaceRegistriesGet(ctx context.Context, _ gen.ListWorkspaceRegistriesV1WorkspaceRegistriesGetRequestObject) (gen.ListWorkspaceRegistriesV1WorkspaceRegistriesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	rs, err := s.svc.ListRegistries(ctx, c.Workspace, false, "", "workspace")
	if err != nil {
		return nil, err
	}
	return ok(registries(rs)), nil
}

func (s *Server) GetWorkspaceRegistryV1WorkspaceRegistriesRegistryIdGet(ctx context.Context, rq gen.GetWorkspaceRegistryV1WorkspaceRegistriesRegistryIdGetRequestObject) (gen.GetWorkspaceRegistryV1WorkspaceRegistriesRegistryIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	r, found, err := s.svc.WorkspaceRegistry(ctx, c.Workspace, rq.RegistryId.String())
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, service.ErrRegistryNotFound()
	}
	return ok(registryJSON(r)), nil
}
