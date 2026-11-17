package service

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
)

// InstanceView is an instance with its configuration, provider spec and model spec, as loaded.
type InstanceView struct {
	domain.Instance
	Config   *domain.Config
	Provider *catalogapi.ProviderSpec
	Model    *catalogapi.ModelSpec
	IconURL  *string
}

// IconURL is build_provider_icon_url: a full URL passes, an id names a built-in SVG.
func (s *Service) IconURL(icon *string) *string {
	if icon == nil || *icon == "" {
		return nil
	}
	if strings.HasPrefix(*icon, "http://") || strings.HasPrefix(*icon, "https://") {
		return icon
	}
	u := strings.TrimRight(s.d.APIURL, "/") + "/static/icons/providers/" + *icon + ".svg"
	return &u
}

func (s *Service) instanceViews(ctx context.Context, sess db.Session, ws scope.Workspace, ins []domain.Instance) ([]InstanceView, error) {
	cfgIDs := make([]uuid.UUID, 0, len(ins))
	specIDs := make([]uuid.UUID, 0, len(ins))
	for _, in := range ins {
		cfgIDs = append(cfgIDs, uuid.MustParse(in.ProviderConfigID))
		specIDs = append(specIDs, uuid.MustParse(in.ModelSpecID))
	}
	cfgs, err := s.st.ConfigsOfInstances(ctx, sess, cfgIDs)
	if err != nil {
		return nil, err
	}
	provIDs := make([]uuid.UUID, 0, len(cfgs))
	for _, c := range cfgs {
		provIDs = append(provIDs, uuid.MustParse(c.ProviderSpecID))
	}
	provs, err := s.d.Catalog.ProviderSpecs(ctx, ws, provIDs)
	if err != nil {
		return nil, err
	}
	models, err := s.d.Catalog.ModelSpecs(ctx, ws, specIDs)
	if err != nil {
		return nil, err
	}
	out := make([]InstanceView, len(ins))
	for i, in := range ins {
		v := InstanceView{Instance: in}
		if c, ok := cfgs[in.ProviderConfigID]; ok {
			v.Config = &c
			if p, ok := provs[uuid.MustParse(c.ProviderSpecID)]; ok {
				v.Provider = &p
				v.IconURL = s.IconURL(p.Icon)
			}
		}
		if m, ok := models[uuid.MustParse(in.ModelSpecID)]; ok {
			v.Model = &m
		}
		out[i] = v
	}
	return out, nil
}

func (s *Service) instanceView(ctx context.Context, ws scope.Workspace, id uuid.UUID) (InstanceView, bool, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return InstanceView{}, false, err
	}
	defer release()
	in, ok, err := s.st.Instance(ctx, sess, id)
	if err != nil || !ok {
		return InstanceView{}, ok, err
	}
	vs, err := s.instanceViews(ctx, sess, ws, []domain.Instance{in})
	if err != nil {
		return InstanceView{}, false, err
	}
	return vs[0], true, nil
}

// Instance is get_model_instance.
func (s *Service) Instance(ctx context.Context, id uuid.UUID) (InstanceView, bool, error) {
	ws, _, err := caller(ctx)
	if err != nil {
		return InstanceView{}, false, err
	}
	return s.instanceView(ctx, ws, id)
}

// InstanceFilter is list_model_instances' query.
type InstanceFilter struct {
	store.InstanceFilter
	Kind *string
}

// Instances is list_model_instances; a kind keeps the visible instances whose spec is of it.
func (s *Service) Instances(ctx context.Context, f InstanceFilter) ([]InstanceView, error) {
	ws, _, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	sf := f.InstanceFilter
	if f.Kind != nil {
		bySpec, err := s.st.VisibleInstanceSpecs(ctx, sess)
		if err != nil {
			return nil, err
		}
		specIDs := make([]uuid.UUID, 0, len(bySpec))
		for _, sp := range bySpec {
			specIDs = append(specIDs, sp)
		}
		specs, err := s.d.Catalog.ModelSpecs(ctx, ws, specIDs)
		if err != nil {
			return nil, err
		}
		sf.ByIDs, sf.IDs = true, []uuid.UUID{}
		for id, sp := range bySpec {
			if m, ok := specs[sp]; ok && m.Kind == *f.Kind {
				sf.IDs = append(sf.IDs, id)
			}
		}
	}
	ins, err := s.st.Instances(ctx, sess, sf)
	if err != nil {
		return nil, err
	}
	return s.instanceViews(ctx, sess, ws, ins)
}

// CreateInstance is create_model_instance: a catalog item id is resolved to the workspace's copy.
func (s *Service) CreateInstance(ctx context.Context, n domain.NewInstance) (InstanceView, error) {
	ws, userID, err := caller(ctx)
	if err != nil {
		return InstanceView{}, err
	}
	cfgID, err := uuid.Parse(n.ProviderConfigID)
	if err != nil {
		return InstanceView{}, err
	}
	specID, err := uuid.Parse(n.ModelSpecID)
	if err != nil {
		return InstanceView{}, err
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return InstanceView{}, err
	}
	cfg, ok, err := s.st.Config(ctx, sess, cfgID)
	release()
	if err != nil {
		return InstanceView{}, err
	}
	if !ok {
		return InstanceView{}, &NotFoundError{Detail: fmt.Sprintf("Provider config %s not found", cfgID)}
	}
	spec, ok, err := s.d.Catalog.UsableModelSpec(ctx, ws, specID)
	if err != nil {
		return InstanceView{}, err
	}
	if !ok && !cfg.PlatformManaged() {
		if spec, ok, err = s.d.Catalog.CopyCatalogModelSpec(ctx, ws, userID, specID); err != nil {
			return InstanceView{}, err
		}
	}
	if !ok {
		return InstanceView{}, &NotFoundError{Detail: fmt.Sprintf("Model spec %s not found", specID)}
	}
	if !platformOffers(cfg, spec) {
		return InstanceView{}, &BadRequestError{Detail: notOffered(specID.String(), cfg.ID)}
	}
	id := uuid.New()
	in := domain.Instance{
		ID: id.String(), ProviderConfigID: cfgID.String(), ModelSpecID: spec.ID.String(), Name: n.Name,
		Description: n.Description, IsActive: true, IsPublic: n.IsPublic, CreatedBy: userID,
	}
	if err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return s.st.InsertInstance(ctx, sess, in, s.d.Now())
	}); err != nil {
		return InstanceView{}, err
	}
	v, _, err := s.instanceView(ctx, ws, id)
	return v, err
}

// BulkFailure is ModelInstanceBulkFailure.
type BulkFailure struct {
	Index       int
	ModelSpecID string
	Error       string
}

// CreateInstances is the bulk route: each item on its own; unknown or unpriced items fail alone.
func (s *Service) CreateInstances(ctx context.Context, items []domain.NewInstance) ([]InstanceView, []BulkFailure, error) {
	ok := []InstanceView{}
	failed := []BulkFailure{}
	for i, n := range items {
		v, err := s.CreateInstance(ctx, n)
		var nf *NotFoundError
		var br *BadRequestError
		var unpriced *catalogapi.ModelPricingNotConfiguredError
		switch {
		case err == nil:
			ok = append(ok, v)
		case errors.As(err, &nf):
			failed = append(failed, BulkFailure{Index: i, ModelSpecID: n.ModelSpecID, Error: nf.Detail})
		case errors.As(err, &br):
			failed = append(failed, BulkFailure{Index: i, ModelSpecID: n.ModelSpecID, Error: br.Detail})
		case errors.As(err, &unpriced):
			failed = append(failed, BulkFailure{Index: i, ModelSpecID: n.ModelSpecID, Error: unpriced.Error()})
		default:
			return nil, nil, err
		}
	}
	return ok, failed, nil
}

// DeleteInstance removes one of the workspace's own instances. The route's
// require_permission names an ungoverned type, so any member passes it.
func (s *Service) DeleteInstance(ctx context.Context, id uuid.UUID) (bool, error) {
	ws, _, err := caller(ctx)
	if err != nil {
		return false, err
	}
	c, _ := authn.CallerFrom(ctx)
	if err := authz.NewPermissions(nil, nil).Require(ctx, c, "delete", "model_instance", id.String()); err != nil {
		return false, err
	}
	deleted := false
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		deleted, err = s.st.DeleteInstance(ctx, sess, id)
		return err
	})
	return deleted, err
}

// SpecIDsInUse is what catalog's offered_to needs of models.
func (s *Service) ProviderSpecIDsWithVisibleConfigs(ctx context.Context, ws scope.Workspace) ([]uuid.UUID, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	return s.st.ProviderSpecIDsWithVisibleConfigs(ctx, sess)
}

// ModelSpecIDsWithVisibleInstances are the specs of the instances the workspace reads.
func (s *Service) ModelSpecIDsWithVisibleInstances(ctx context.Context, ws scope.Workspace) ([]uuid.UUID, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	m, err := s.st.VisibleInstanceSpecs(ctx, sess)
	if err != nil {
		return nil, err
	}
	seen := map[uuid.UUID]bool{}
	out := []uuid.UUID{}
	for _, sp := range m {
		if !seen[sp] {
			seen[sp] = true
			out = append(out, sp)
		}
	}
	return out, nil
}

// platformOffers holds unless a platform-supplied config would carry a spec the
// platform does not offer for that provider: a tenant's own spec priced as it likes.
func platformOffers(c domain.Config, m catalogapi.ModelSpec) bool {
	return !c.PlatformManaged() || (m.WorkspaceID == PlatformWorkspaceID && m.ProviderSpecID.String() == c.ProviderSpecID)
}

func notOffered(specID, configID string) string {
	return fmt.Sprintf("Model spec %s is not offered by the platform-supplied provider config %s", specID, configID)
}
