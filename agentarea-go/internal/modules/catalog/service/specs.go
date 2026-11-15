package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

// Specs implements api.Specs over the store.
type Specs struct {
	s *Service
}

var _ api.Specs = Specs{}

func (s *Service) read(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

func (x Specs) ProviderSpec(ctx context.Context, ws scope.Workspace, id uuid.UUID) (p api.ProviderSpec, ok bool, err error) {
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		p, ok, err = x.s.d.Specs.ProviderSpec(ctx, sess, id)
		return err
	})
	return p, ok, err
}

func (x Specs) ProviderSpecByKey(ctx context.Context, ws scope.Workspace, key string) (p api.ProviderSpec, ok bool, err error) {
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		p, ok, err = x.s.d.Specs.ProviderSpecByKey(ctx, sess, key)
		return err
	})
	return p, ok, err
}

func (x Specs) ProviderSpecs(ctx context.Context, ws scope.Workspace, ids []uuid.UUID) (out map[uuid.UUID]api.ProviderSpec, err error) {
	if len(ids) == 0 {
		return map[uuid.UUID]api.ProviderSpec{}, nil
	}
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		out, err = x.s.d.Specs.ProviderSpecs(ctx, sess, ids)
		return err
	})
	return out, err
}

func (x Specs) ModelSpecs(ctx context.Context, ws scope.Workspace, ids []uuid.UUID) (out map[uuid.UUID]api.ModelSpec, err error) {
	if len(ids) == 0 {
		return map[uuid.UUID]api.ModelSpec{}, nil
	}
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		out, err = x.s.d.Specs.ModelSpecs(ctx, sess, ids)
		return err
	})
	return out, err
}

func (x Specs) UsableModelSpec(ctx context.Context, ws scope.Workspace, id uuid.UUID) (m api.ModelSpec, ok bool, err error) {
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		m, ok, err = x.s.d.Specs.UsableModelSpec(ctx, sess, id)
		return err
	})
	return m, ok, err
}

// CopyCatalogModelSpec is get_or_copy_catalog_spec (model_spec_repository.py:254).
func (x Specs) CopyCatalogModelSpec(ctx context.Context, ws scope.Workspace, userID string, itemID uuid.UUID) (api.ModelSpec, bool, error) {
	var out api.ModelSpec
	var found bool
	err := x.s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		st := x.s.d.Specs
		item, ok, err := st.CatalogModel(ctx, sess, itemID)
		if err != nil || !ok || item.ProviderSpecID == nil {
			return err
		}
		proj, err := ProjectCatalogModel(item)
		if err != nil {
			return err
		}
		pid, name := *item.ProviderSpecID, proj.Spec.ModelName
		if out, found, err = st.ModelSpecByProviderAndName(ctx, sess, pid, name); err != nil || found {
			return err
		}
		items, err := st.CatalogModels(ctx, sess)
		if err != nil {
			return err
		}
		var preferred *CatalogModelSpec
		for _, it := range items {
			p, err := ProjectCatalogModel(it)
			if err != nil {
				return err
			}
			if p.HasProvider && p.Spec.ProviderSpecID == pid && p.Spec.ModelName == name {
				preferred = &p
				break
			}
		}
		if preferred == nil {
			return nil
		}
		if !preferred.Priced() {
			return &api.ModelPricingNotConfiguredError{ModelName: name}
		}
		m := preferred.Spec
		if err := st.InsertModelSpecIfAbsent(ctx, sess, store.NewModelSpec{
			ID: uuid.New(), ProviderSpecID: pid, CreatedBy: userID, ModelName: name, DisplayName: m.DisplayName,
			Description: m.Description, Kind: m.Kind, ContextWindow: m.ContextWindow, MaxOutputTokens: m.MaxOutputTokens,
			InputCostPerToken: m.InputCostPerToken, OutputCostPerToken: m.OutputCostPerToken,
			CachedInputCostPerToken:        m.CachedInputCostPerToken,
			CacheCreationInputCostPerToken: m.CacheCreationInputCostPerToken,
			SupportsFunctionCalling:        m.SupportsFunctionCalling, SupportsVision: m.SupportsVision,
			SupportsReasoning: m.SupportsReasoning, ReasoningEfforts: m.ReasoningEfforts, IsActive: m.IsActive,
		}, x.s.d.Now()); err != nil {
			return err
		}
		out, found, err = st.ModelSpecByProviderAndName(ctx, sess, pid, name)
		return err
	})
	if err != nil {
		return api.ModelSpec{}, false, err
	}
	return out, found, nil
}

// UpsertModelSpecs is upsert_many_by_provider_and_model (model_spec_repository.py:397).
func (x Specs) UpsertModelSpecs(ctx context.Context, ws scope.Workspace, userID string, providerSpecID uuid.UUID, rows []api.DiscoveredSpec) (map[string]api.Upserted, error) {
	byName := map[string]api.DiscoveredSpec{}
	var names []string
	for _, r := range rows {
		if _, seen := byName[r.ModelName]; !seen {
			names = append(names, r.ModelName)
		}
		byName[r.ModelName] = r
	}
	written := map[string]api.Upserted{}
	if len(names) == 0 {
		return written, nil
	}
	err := x.s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		st := x.s.d.Specs
		existing, err := st.ModelSpecIDs(ctx, sess, providerSpecID, names)
		if err != nil {
			return err
		}
		now := x.s.d.Now()
		for _, name := range names {
			r := byName[name]
			if id, ok := existing[name]; ok {
				written[name] = api.Upserted{ID: id}
				if err := st.UpdateDiscoveredSpec(ctx, sess, id, r, now); err != nil {
					return err
				}
				continue
			}
			id := uuid.New()
			written[name] = api.Upserted{ID: id, IsNew: true}
			fc, vision, reasoning := r.SupportsFunctionCalling, r.SupportsVision, r.SupportsReasoning
			kind := r.Kind
			if kind == "" {
				kind = KindChat
			}
			if err := st.InsertModelSpec(ctx, sess, store.NewModelSpec{
				ID: id, ProviderSpecID: providerSpecID, CreatedBy: userID, ModelName: name, DisplayName: r.DisplayName,
				Description: r.Description, Kind: kind, ContextWindow: r.ContextWindow, MaxOutputTokens: r.MaxOutputTokens,
				InputCostPerToken: r.InputCostPerToken, OutputCostPerToken: r.OutputCostPerToken,
				CachedInputCostPerToken:        r.CachedInputCostPerToken,
				CacheCreationInputCostPerToken: r.CacheCreationInputCostPerToken,
				SupportsFunctionCalling:        &fc, SupportsVision: &vision, SupportsReasoning: &reasoning, IsActive: true,
			}, now); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return written, nil
}

// Model kinds (ModelKind).
const (
	KindChat      = "chat"
	KindEmbedding = "embedding"
	KindImage     = "image"
	KindVideo     = "video"
	KindDecision  = "decision"
)

// ValidKind reports a ModelKind value.
func ValidKind(k string) bool {
	switch k {
	case KindChat, KindEmbedding, KindImage, KindVideo, KindDecision:
		return true
	}
	return false
}

// PricedPerToken is ModelKind.priced_per_token.
func PricedPerToken(k string) bool { return k == KindChat || k == KindEmbedding }

// CatalogModelSpec is _project_catalog_model_spec: a read-only spec whose id
// is the catalog item's.
type CatalogModelSpec struct {
	Spec         api.ModelSpec
	HasProvider  bool
	ProviderKey  *string
	ProviderName *string
}

// Priced is _is_priced.
func (c CatalogModelSpec) Priced() bool {
	if !PricedPerToken(c.Spec.Kind) {
		return true
	}
	return c.Spec.InputCostPerToken != nil && c.Spec.OutputCostPerToken != nil
}

// ErrProjection is a catalog model item Python fails to project (a KeyError
// or ValueError in _project_catalog_model_spec): a 500.
var ErrProjection = errors.New("catalog model item cannot be projected")

// optionalMoney is to_optional_money over a decoded JSON value.
func optionalMoney(v any, present bool) (*money.Decimal, error) {
	if !present || v == nil {
		return nil, nil
	}
	var text string
	switch t := v.(type) {
	case string:
		text = t
	case json.Number:
		text = t.String()
	case wirejson.Float:
		text = wirejson.FormatFloat(float64(t))
	default:
		return nil, fmt.Errorf("%w: %v is not a price", ErrProjection, v)
	}
	d, err := money.Parse(text)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrProjection, err)
	}
	return &d, nil
}

func optionalInt(v any, present bool) (*int, error) {
	if !present || v == nil {
		return nil, nil
	}
	n, ok := v.(json.Number)
	if !ok {
		return nil, fmt.Errorf("%w: %v is not an integer", ErrProjection, v)
	}
	i, err := strconv.Atoi(n.String())
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrProjection, err)
	}
	return &i, nil
}

func flag(o wirejson.Object, key string, def bool) (*bool, error) {
	v, ok := o.Get(key)
	if !ok {
		return &def, nil
	}
	if v == nil {
		return nil, nil
	}
	b, isBool := v.(bool)
	if !isBool {
		return nil, fmt.Errorf("%w: %s is not a boolean", ErrProjection, key)
	}
	return &b, nil
}

func pyTruthyString(v any) (string, bool) {
	s, ok := v.(string)
	return s, ok && s != ""
}

// ProjectCatalogModel is _project_catalog_model_spec (model_spec_repository.py:36).
func ProjectCatalogModel(item store.CatalogModel) (CatalogModelSpec, error) {
	o := wirejson.Object{}
	if v, err := wirejson.Unmarshal(item.Spec); err == nil {
		if obj, ok := v.(wirejson.Object); ok {
			o = obj
		}
	}
	kind := KindChat
	if v, ok := o.Get("kind"); ok {
		s, isStr := v.(string)
		if !isStr || !ValidKind(s) {
			return CatalogModelSpec{}, fmt.Errorf("%w: kind %v", ErrProjection, v)
		}
		kind = s
	}
	m := api.ModelSpec{
		ID: item.ID, ModelName: item.Name, DisplayName: item.Name, Description: item.Description, Kind: kind,
		CreatedAt: item.CreatedAt, UpdatedAt: item.UpdatedAt, IsActive: true,
	}
	if s, ok := pyTruthyString(firstOf(o, "model_name")); ok {
		m.ModelName = s
	}
	if m.Description == nil {
		if v, ok := o.Get("description"); ok && v != nil {
			s, isStr := v.(string)
			if !isStr {
				return CatalogModelSpec{}, fmt.Errorf("%w: description", ErrProjection)
			}
			m.Description = &s
		}
	}
	var err error
	cw, cwSet := o.Get("context_window")
	if PricedPerToken(kind) && !cwSet {
		return CatalogModelSpec{}, fmt.Errorf("%w: context_window", ErrProjection)
	}
	if m.ContextWindow, err = optionalInt(cw, cwSet); err != nil {
		return CatalogModelSpec{}, err
	}
	if m.MaxOutputTokens, err = optionalInt(o.Get("max_output_tokens")); err != nil {
		return CatalogModelSpec{}, err
	}
	for _, p := range []struct {
		key string
		dst **money.Decimal
	}{
		{"input_cost_per_token", &m.InputCostPerToken}, {"output_cost_per_token", &m.OutputCostPerToken},
		{"cached_input_cost_per_token", &m.CachedInputCostPerToken},
		{"cache_creation_input_cost_per_token", &m.CacheCreationInputCostPerToken},
	} {
		if *p.dst, err = optionalMoney(o.Get(p.key)); err != nil {
			return CatalogModelSpec{}, err
		}
	}
	if m.SupportsFunctionCalling, err = flag(o, "supports_function_calling", false); err != nil {
		return CatalogModelSpec{}, err
	}
	if m.SupportsVision, err = flag(o, "supports_vision", false); err != nil {
		return CatalogModelSpec{}, err
	}
	if m.SupportsReasoning, err = flag(o, "supports_reasoning", false); err != nil {
		return CatalogModelSpec{}, err
	}
	if v, ok := o.Get("reasoning_efforts"); ok && v != nil {
		arr, isArr := v.([]any)
		if !isArr {
			return CatalogModelSpec{}, fmt.Errorf("%w: reasoning_efforts", ErrProjection)
		}
		m.ReasoningEfforts = []string{}
		for _, e := range arr {
			s, isStr := e.(string)
			if !isStr {
				return CatalogModelSpec{}, fmt.Errorf("%w: reasoning_efforts", ErrProjection)
			}
			m.ReasoningEfforts = append(m.ReasoningEfforts, s)
		}
	}
	if active, err := flag(o, "is_active", true); err != nil {
		return CatalogModelSpec{}, err
	} else if active != nil {
		m.IsActive = *active
	} else {
		m.IsActive = false
	}
	out := CatalogModelSpec{Spec: m, ProviderKey: item.ProviderKey, ProviderName: item.ProviderName}
	if out.ProviderKey == nil {
		if s, ok := pyTruthyString(firstOf(o, "provider_key")); ok {
			out.ProviderKey = &s
		}
	}
	if item.ProviderSpecID != nil {
		out.HasProvider = true
		out.Spec.ProviderSpecID = *item.ProviderSpecID
	}
	return out, nil
}

func firstOf(o wirejson.Object, key string) any {
	v, _ := o.Get(key)
	return v
}
