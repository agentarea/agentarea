package service

import (
	"context"
	"errors"
	"sort"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
)

// ProviderView is a provider spec with the caller's workspace's model specs
// of it and its icon URL.
type ProviderView struct {
	api.ProviderSpec
	IconURL *string
	Models  []api.ModelSpec
}

// ModelView is a model spec as ModelSpecResponse renders it, with its
// provider's name and key when loaded.
type ModelView struct {
	api.ModelSpec
	ProviderName *string
	ProviderKey  *string
}

// ErrNoSpecUse: the provider lists were reached with no models port.
var ErrNoSpecUse = errors.New("catalog: provider-spec lists need models' SpecUse")

// ProviderIconURL is build_provider_icon_url.
func (s *Service) ProviderIconURL(icon *string) *string {
	return IconURL(s.d.APIURL, ProviderIcons, icon)
}

func (s *Service) withModels(ctx context.Context, sess db.Session, specs []api.ProviderSpec) ([]ProviderView, error) {
	out := make([]ProviderView, len(specs))
	if len(specs) == 0 {
		return out, nil
	}
	ids := make([]uuid.UUID, len(specs))
	for i, p := range specs {
		ids[i] = p.ID
	}
	models, err := s.d.Specs.ModelSpecsOfProviders(ctx, sess, ids)
	if err != nil {
		return nil, err
	}
	byProvider := map[uuid.UUID][]api.ModelSpec{}
	for _, m := range models {
		byProvider[m.ProviderSpecID] = append(byProvider[m.ProviderSpecID], m)
	}
	for i, p := range specs {
		ms := byProvider[p.ID]
		if ms == nil {
			ms = []api.ModelSpec{}
		}
		out[i] = ProviderView{ProviderSpec: p, IconURL: s.ProviderIconURL(p.Icon), Models: ms}
	}
	return out, nil
}

// ProviderSpecs is list_provider_specs: what is offered to ws, with models.
func (s *Service) ProviderSpecs(ctx context.Context, ws scope.Workspace, isBuiltin *bool) ([]ProviderView, error) {
	if s.d.SpecUse == nil {
		return nil, ErrNoSpecUse
	}
	configs, err := s.d.SpecUse.ProviderSpecIDsWithVisibleConfigs(ctx, ws)
	if err != nil {
		return nil, err
	}
	instances, err := s.d.SpecUse.ModelSpecIDsWithVisibleInstances(ctx, ws)
	if err != nil {
		return nil, err
	}
	var out []ProviderView
	err = s.read(ctx, ws, func(sess db.Session) error {
		specs, err := s.d.Specs.OfferedProviderSpecs(ctx, sess, isBuiltin, configs, instances)
		if err != nil {
			return err
		}
		out, err = s.withModels(ctx, sess, specs)
		return err
	})
	return out, err
}

// ProviderSpecWithModels is get_provider_spec (byKey false) or
// get_provider_spec_by_key: no workspace filter, no offered_to.
func (s *Service) ProviderSpecWithModels(ctx context.Context, ws scope.Workspace, id uuid.UUID, key string, byKey bool) (ProviderView, bool, error) {
	var out ProviderView
	var found bool
	err := s.read(ctx, ws, func(sess db.Session) error {
		var p api.ProviderSpec
		var err error
		if byKey {
			p, found, err = s.d.Specs.ProviderSpecByKey(ctx, sess, key)
		} else {
			p, found, err = s.d.Specs.ProviderSpec(ctx, sess, id)
		}
		if err != nil || !found {
			return err
		}
		views, err := s.withModels(ctx, sess, []api.ProviderSpec{p})
		if err != nil {
			return err
		}
		out = views[0]
		return nil
	})
	return out, found, err
}

func (s *Service) tenantViews(ctx context.Context, sess db.Session, specs []api.ModelSpec) ([]ModelView, error) {
	ids := make([]uuid.UUID, 0, len(specs))
	for _, m := range specs {
		ids = append(ids, m.ProviderSpecID)
	}
	provs := map[uuid.UUID]api.ProviderSpec{}
	if len(ids) > 0 {
		var err error
		if provs, err = s.d.Specs.ProviderSpecs(ctx, sess, ids); err != nil {
			return nil, err
		}
	}
	out := make([]ModelView, len(specs))
	for i, m := range specs {
		v := ModelView{ModelSpec: m}
		if p, ok := provs[m.ProviderSpecID]; ok {
			name, key := p.Name, p.ProviderKey
			v.ProviderName, v.ProviderKey = &name, &key
		}
		out[i] = v
	}
	return out, nil
}

func projectionView(p CatalogModelSpec) ModelView {
	v := ModelView{ModelSpec: p.Spec}
	if p.ProviderKey != nil {
		key := *p.ProviderKey
		name := key
		if p.ProviderName != nil && *p.ProviderName != "" {
			name = *p.ProviderName
		}
		v.ProviderName, v.ProviderKey = &name, &key
	}
	return v
}

func modelKey(p CatalogModelSpec) string {
	if !p.HasProvider {
		return "None\x00" + p.Spec.ModelName
	}
	return p.Spec.ProviderSpecID.String() + "\x00" + p.Spec.ModelName
}

// usableProjection is a catalog model a workspace could add: priced, with its
// provider installed.
func usableProjection(p CatalogModelSpec) bool { return p.HasProvider && p.Priced() }

// ModelFilter is list_specs' filters; nil is unset.
type ModelFilter = store.SpecFilter

// ModelSpecs is ModelSpecRepository.list_specs: ws's own rows newest first,
// then the catalog projections they do not shadow, by display name; at most
// 100. A catalog model whose provider is not installed is left out.
func (s *Service) ModelSpecs(ctx context.Context, ws scope.Workspace, f ModelFilter) ([]ModelView, error) {
	var out []ModelView
	err := s.read(ctx, ws, func(sess db.Session) error {
		own, err := s.d.Specs.OwnModelSpecs(ctx, sess, f)
		if err != nil {
			return err
		}
		if out, err = s.tenantViews(ctx, sess, own); err != nil {
			return err
		}
		keys, err := s.d.Specs.OwnModelKeys(ctx, sess)
		if err != nil {
			return err
		}
		seen := map[string]bool{}
		for k := range keys {
			seen[k.ProviderSpecID.String()+"\x00"+k.ModelName] = true
		}
		items, err := s.d.Specs.CatalogModels(ctx, sess)
		if err != nil {
			return err
		}
		var projections []ModelView
		for _, it := range items {
			p, err := ProjectCatalogModel(it)
			if err != nil {
				return err
			}
			key := modelKey(p)
			if seen[key] {
				continue
			}
			seen[key] = true
			if !usableProjection(p) {
				continue
			}
			if f.ProviderSpecID != nil && p.Spec.ProviderSpecID != *f.ProviderSpecID {
				continue
			}
			if f.IsActive != nil && p.Spec.IsActive != *f.IsActive {
				continue
			}
			if f.Kind != nil && p.Spec.Kind != *f.Kind {
				continue
			}
			projections = append(projections, projectionView(p))
		}
		sort.SliceStable(projections, func(i, j int) bool { return projections[i].DisplayName < projections[j].DisplayName })
		out = append(out, projections...)
		if len(out) > 100 {
			out = out[:100]
		}
		return nil
	})
	return out, err
}

func (s *Service) modelWithRelations(ctx context.Context, sess db.Session, id uuid.UUID) (ModelView, bool, bool, error) {
	m, ok, err := s.d.Specs.OwnModelSpec(ctx, sess, id)
	if err != nil {
		return ModelView{}, false, false, err
	}
	if ok {
		vs, err := s.tenantViews(ctx, sess, []api.ModelSpec{m})
		if err != nil {
			return ModelView{}, false, false, err
		}
		return vs[0], true, true, nil
	}
	it, ok, err := s.d.Specs.CatalogModel(ctx, sess, id)
	if err != nil || !ok {
		return ModelView{}, false, false, err
	}
	p, err := ProjectCatalogModel(it)
	if err != nil || !p.HasProvider {
		return ModelView{}, false, false, err
	}
	return projectionView(p), true, false, nil
}

// ModelSpec is get_with_relations: ws's own row, else the catalog projection.
func (s *Service) ModelSpec(ctx context.Context, ws scope.Workspace, id uuid.UUID) (ModelView, bool, error) {
	var out ModelView
	var found bool
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		out, found, _, err = s.modelWithRelations(ctx, sess, id)
		return err
	})
	return out, found, err
}

// ModelSpecByName is get_by_provider_and_model: ws's own newest row only.
func (s *Service) ModelSpecByName(ctx context.Context, ws scope.Workspace, providerSpecID uuid.UUID, name string) (ModelView, bool, error) {
	var out ModelView
	var found bool
	err := s.read(ctx, ws, func(sess db.Session) error {
		m, ok, err := s.d.Specs.ModelSpecByProviderAndName(ctx, sess, providerSpecID, name)
		if err != nil || !ok {
			return err
		}
		vs, err := s.tenantViews(ctx, sess, []api.ModelSpec{m})
		if err != nil {
			return err
		}
		out, found = vs[0], true
		return nil
	})
	return out, found, err
}

// NewModelSpec is ModelSpecCreate after validation.
type NewModelSpec struct {
	ProviderSpecID uuid.UUID
	ModelName      string
	Fields         store.SpecFields
}

func duplicateSpec(name string) error {
	return &ConflictError{Detail: "Model specification '" + name + "' already exists for this provider"}
}

func integrityError(err error) bool {
	_, ok := store.Constraint(err)
	return ok
}

func uniqueViolation(err error) bool {
	code, _ := store.Constraint(err)
	return code == store.UniqueViolation
}

func (s *Service) requireProvider(ctx context.Context, ws scope.Workspace, id uuid.UUID) error {
	_, found, err := s.ProviderSpecWithModels(ctx, ws, id, "", false)
	if err == nil && !found {
		err = ErrProviderNotFound()
	}
	return err
}

// ErrProviderNotFound is the provider-specs 404.
func ErrProviderNotFound() error { return &NotFoundError{Detail: "Provider specification not found"} }

// CreateModelSpec is create_model_spec: 404 for an unknown provider, 409 on
// a duplicate.
func (s *Service) CreateModelSpec(ctx context.Context, ws scope.Workspace, userID string, n NewModelSpec) (ModelView, error) {
	if err := s.requireProvider(ctx, ws, n.ProviderSpecID); err != nil {
		return ModelView{}, err
	}
	_, exists, err := s.ModelSpecByName(ctx, ws, n.ProviderSpecID, n.ModelName)
	if err != nil {
		return ModelView{}, err
	}
	if exists {
		return ModelView{}, duplicateSpec(n.ModelName)
	}
	id := uuid.New()
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return s.d.Specs.CreateModelSpec(ctx, sess, id, n.ProviderSpecID, userID, n.ModelName, n.Fields, s.d.Now())
	})
	if uniqueViolation(err) {
		return ModelView{}, duplicateSpec(n.ModelName)
	}
	if err != nil {
		return ModelView{}, err
	}
	out, _, err := s.ModelSpec(ctx, ws, id)
	return out, err
}

// ErrModelSpecNotFound is the model-specs 404.
func ErrModelSpecNotFound() error { return &NotFoundError{Detail: "Model specification not found"} }

func changed(m api.ModelSpec, f store.SpecFields) bool {
	str := func(p *string, cur *string) bool { return p != nil && (cur == nil || *cur != *p) }
	num := func(p *int, cur *int) bool { return p != nil && (cur == nil || *cur != *p) }
	if (f.DisplayName != nil && *f.DisplayName != m.DisplayName) || str(f.Description, m.Description) ||
		(f.Kind != nil && *f.Kind != m.Kind) || num(f.ContextWindow, m.ContextWindow) ||
		num(f.MaxOutputTokens, m.MaxOutputTokens) || str(f.DefaultContextStrategy, m.DefaultContextStrategy) ||
		(f.IsActive != nil && *f.IsActive != m.IsActive) {
		return true
	}
	for _, p := range []struct{ next, cur *money.Decimal }{
		{f.InputCostPerToken, m.InputCostPerToken}, {f.OutputCostPerToken, m.OutputCostPerToken},
		{f.CachedInputCostPerToken, m.CachedInputCostPerToken},
		{f.CacheCreationInputCostPerToken, m.CacheCreationInputCostPerToken},
	} {
		if p.next != nil && (p.cur == nil || !p.cur.Equal(*p.next)) {
			return true
		}
	}
	return false
}

// UpdateModelSpec is update_model_spec: the fields given onto ws's own row.
// A catalog projection is read-only: not found, as for delete.
func (s *Service) UpdateModelSpec(ctx context.Context, ws scope.Workspace, id uuid.UUID, f store.SpecFields) (ModelView, error) {
	var out ModelView
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		cur, found, own, err := s.modelWithRelations(ctx, sess, id)
		if err != nil {
			return err
		}
		if !found || !own {
			return ErrModelSpecNotFound()
		}
		if _, err := s.d.Specs.UpdateModelSpec(ctx, sess, id, f, changed(cur.ModelSpec, f), s.d.Now()); err != nil {
			return err
		}
		out, found, _, err = s.modelWithRelations(ctx, sess, id)
		if err == nil && !found {
			err = ErrModelSpecNotFound()
		}
		return err
	})
	return out, err
}

// DeleteModelSpec is delete_model_spec on ws's own row.
func (s *Service) DeleteModelSpec(ctx context.Context, ws scope.Workspace, id uuid.UUID) error {
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		ok, err := s.d.Specs.DeleteModelSpec(ctx, sess, id)
		if err == nil && !ok {
			err = ErrModelSpecNotFound()
		}
		return err
	})
}

// UpsertModelSpec is upsert_by_provider_and_model_kwargs: ws's newest row
// for the model takes the fields given, else one is created.
func (s *Service) UpsertModelSpec(ctx context.Context, ws scope.Workspace, userID string, n NewModelSpec) (ModelView, error) {
	if err := s.requireProvider(ctx, ws, n.ProviderSpecID); err != nil {
		return ModelView{}, err
	}
	var id uuid.UUID
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		m, ok, err := s.d.Specs.ModelSpecByProviderAndName(ctx, sess, n.ProviderSpecID, n.ModelName)
		if err != nil {
			return err
		}
		if ok {
			id = m.ID
			_, err = s.d.Specs.UpdateModelSpec(ctx, sess, id, n.Fields, changed(m, n.Fields), s.d.Now())
			return err
		}
		id = uuid.New()
		return s.d.Specs.CreateModelSpec(ctx, sess, id, n.ProviderSpecID, userID, n.ModelName, n.Fields, s.d.Now())
	})
	if err != nil {
		return ModelView{}, err
	}
	out, _, err := s.ModelSpec(ctx, ws, id)
	return out, err
}
