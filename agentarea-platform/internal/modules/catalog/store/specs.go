package store

import (
	"context"
	"encoding/json"
	"errors"
	"math/big"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

//go:generate sqlc generate

// Specs reads provider_specs and model_specs, and the catalog's llm_models
// items they are projected from.
type Specs struct{}

// CatalogModel is a CatalogModelSpecItem: an llm_models item of an active
// registry, its provider resolved by provider_key.
type CatalogModel struct {
	ID             uuid.UUID
	Name           string
	Description    *string
	Version        *string
	Spec           []byte
	CreatedAt      time.Time
	UpdatedAt      time.Time
	ProviderSpecID *uuid.UUID
	ProviderKey    *string
	ProviderName   *string
}

func fromText(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	s := t.String
	return &s
}

func text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func fromInt4(v pgtype.Int4) *int {
	if !v.Valid {
		return nil
	}
	n := int(v.Int32)
	return &n
}

func int4(p *int) pgtype.Int4 {
	if p == nil {
		return pgtype.Int4{}
	}
	return pgtype.Int4{Int32: int32(*p), Valid: true}
}

func fromBool(v pgtype.Bool) *bool {
	if !v.Valid {
		return nil
	}
	b := v.Bool
	return &b
}

func boolean(b bool) pgtype.Bool { return pgtype.Bool{Bool: b, Valid: true} }

// naive is a timestamp without time zone holding t's wall clock, as
// Python's datetime.now() writes it.
// naive is a TIMESTAMP WITHOUT TIME ZONE holding UTC, which the API renders with Z.
func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.UTC().Truncate(time.Microsecond), Valid: true}
}

func fromTimestamp(t pgtype.Timestamp) time.Time { return t.Time }

// decimal is a NUMERIC as asyncpg hands Python a Decimal: its digits at the
// column's scale.
func decimal(n pgtype.Numeric) (*money.Decimal, error) {
	if !n.Valid {
		return nil, nil
	}
	if n.NaN || n.InfinityModifier != pgtype.Finite {
		return nil, errors.New("catalog: non-finite price")
	}
	i := n.Int
	if i == nil {
		i = new(big.Int)
	}
	d, err := money.Parse(i.String() + "e" + big.NewInt(int64(n.Exp)).String())
	if err != nil {
		return nil, err
	}
	return &d, nil
}

func priceText(d *money.Decimal) pgtype.Text {
	if d == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: d.String(), Valid: true}
}

func strings(raw []byte) ([]string, error) {
	if raw == nil {
		return nil, nil
	}
	var out []string
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, err
	}
	return out, nil
}

func providerSpec(r ProviderSpecByIDRow) (api.ProviderSpec, error) {
	efforts, err := strings(r.ReasoningEfforts)
	if err != nil {
		return api.ProviderSpec{}, err
	}
	return api.ProviderSpec{
		ID: r.ID, ProviderKey: r.ProviderKey, ProviderType: r.ProviderType, Name: r.Name, Icon: fromText(r.Icon),
		Description: fromText(r.Description), IsBuiltin: r.IsBuiltin, IsFirstParty: r.IsFirstParty,
		CreatedAt: fromTimestamp(r.CreatedAt), UpdatedAt: fromTimestamp(r.UpdatedAt),
		RequiresAPIKey: r.RequiresApiKey, BaseURL: fromText(r.BaseUrl), Transport: r.Transport, Auth: r.Auth,
		ModelsPath: fromText(r.ModelsPath), ListShape: r.ListShape, ModelsQuery: fromText(r.ModelsQuery),
		ReasoningParam: r.ReasoningParam, ReasoningEfforts: efforts, CacheBreakpoints: r.CacheBreakpoints,
		MaxImageBytes: fromInt4(r.MaxImageBytes), MaxImageEdge: fromInt4(r.MaxImageEdge), PDFInput: r.PdfInput,
	}, nil
}

func modelSpec(r ModelSpecsByIDsRow) (api.ModelSpec, error) {
	out := api.ModelSpec{
		ID: r.ID, ProviderSpecID: r.ProviderSpecID, WorkspaceID: r.WorkspaceID,
		ModelName: r.ModelName, DisplayName: r.DisplayName, Description: fromText(r.Description), Kind: r.Kind,
		ContextWindow: fromInt4(r.ContextWindow), MaxOutputTokens: fromInt4(r.MaxOutputTokens),
		SupportsFunctionCalling: fromBool(r.SupportsFunctionCalling), SupportsVision: fromBool(r.SupportsVision),
		SupportsReasoning: fromBool(r.SupportsReasoning), DefaultContextStrategy: fromText(r.DefaultContextStrategy),
		IsActive: r.IsActive, CreatedAt: fromTimestamp(r.CreatedAt), UpdatedAt: fromTimestamp(r.UpdatedAt),
		ResponsesLite: r.ResponsesLite,
	}
	var err error
	prices := []struct {
		dst **money.Decimal
		src pgtype.Numeric
	}{
		{&out.InputCostPerToken, r.InputCost}, {&out.OutputCostPerToken, r.OutputCost},
		{&out.CachedInputCostPerToken, r.CachedInputCost}, {&out.CacheCreationInputCostPerToken, r.CacheCreationInputCost},
		{&out.OutputCostPerImage, r.ImageCost}, {&out.OutputCostPerVideoPerSecond, r.VideoCost},
	}
	for _, p := range prices {
		if *p.dst, err = decimal(p.src); err != nil {
			return api.ModelSpec{}, err
		}
	}
	if out.ReasoningEfforts, err = strings(r.ReasoningEfforts); err != nil {
		return api.ModelSpec{}, err
	}
	return out, nil
}

func one[T any](v T, err error) (T, bool, error) {
	if errors.Is(err, pgx.ErrNoRows) {
		var zero T
		return zero, false, nil
	}
	return v, err == nil, err
}

// ProviderSpec is the provider spec with this id.
func (Specs) ProviderSpec(ctx context.Context, s db.Session, id uuid.UUID) (api.ProviderSpec, bool, error) {
	r, ok, err := one(New(s.Q()).ProviderSpecByID(ctx, id))
	if !ok || err != nil {
		return api.ProviderSpec{}, false, err
	}
	p, err := providerSpec(r)
	return p, err == nil, err
}

// ProviderSpecByKey is the provider spec with this provider_key.
func (Specs) ProviderSpecByKey(ctx context.Context, s db.Session, key string) (api.ProviderSpec, bool, error) {
	r, ok, err := one(New(s.Q()).ProviderSpecByKey(ctx, key))
	if !ok || err != nil {
		return api.ProviderSpec{}, false, err
	}
	p, err := providerSpec(ProviderSpecByIDRow(r))
	return p, err == nil, err
}

// ProviderSpecs are the provider specs among ids.
func (Specs) ProviderSpecs(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]api.ProviderSpec, error) {
	rows, err := New(s.Q()).ProviderSpecsByIDs(ctx, ids)
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]api.ProviderSpec, len(rows))
	for _, r := range rows {
		p, err := providerSpec(ProviderSpecByIDRow(r))
		if err != nil {
			return nil, err
		}
		out[p.ID] = p
	}
	return out, nil
}

// ModelSpecs are the model specs among ids, whatever their workspace.
func (Specs) ModelSpecs(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]api.ModelSpec, error) {
	rows, err := New(s.Q()).ModelSpecsByIDs(ctx, ids)
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]api.ModelSpec, len(rows))
	for _, r := range rows {
		m, err := modelSpec(r)
		if err != nil {
			return nil, err
		}
		out[m.ID] = m
	}
	return out, nil
}

// UsableModelSpec is the session's workspace's spec or the platform's.
func (Specs) UsableModelSpec(ctx context.Context, s db.Session, id uuid.UUID) (api.ModelSpec, bool, error) {
	r, ok, err := one(New(s.Q()).UsableModelSpec(ctx, UsableModelSpecParams{ID: id, WorkspaceID: s.Workspace().ID()}))
	if !ok || err != nil {
		return api.ModelSpec{}, false, err
	}
	m, err := modelSpec(ModelSpecsByIDsRow(r))
	return m, err == nil, err
}

// ModelSpecByProviderAndName is the workspace's newest spec for the model.
func (Specs) ModelSpecByProviderAndName(ctx context.Context, s db.Session, providerSpecID uuid.UUID, name string) (api.ModelSpec, bool, error) {
	r, ok, err := one(New(s.Q()).ModelSpecByProviderAndName(ctx, ModelSpecByProviderAndNameParams{
		WorkspaceID: s.Workspace().ID(), ProviderSpecID: providerSpecID, ModelName: name,
	}))
	if !ok || err != nil {
		return api.ModelSpec{}, false, err
	}
	m, err := modelSpec(ModelSpecsByIDsRow(r))
	return m, err == nil, err
}

// ModelSpecIDs maps each of names the workspace has a spec for under the
// provider to its id.
func (Specs) ModelSpecIDs(ctx context.Context, s db.Session, providerSpecID uuid.UUID, names []string) (map[string]uuid.UUID, error) {
	rows, err := New(s.Q()).ModelSpecIDsByNames(ctx, ModelSpecIDsByNamesParams{
		WorkspaceID: s.Workspace().ID(), ProviderSpecID: providerSpecID, Names: names,
	})
	if err != nil {
		return nil, err
	}
	out := make(map[string]uuid.UUID, len(rows))
	for _, r := range rows {
		out[r.ModelName] = r.ID
	}
	return out, nil
}

// NewModelSpec is a model_specs row to insert into the session's workspace.
type NewModelSpec struct {
	ID, ProviderSpecID                                                                             uuid.UUID
	CreatedBy                                                                                      string
	ModelName, DisplayName                                                                         string
	Description                                                                                    *string
	Kind                                                                                           string
	ContextWindow, MaxOutputTokens                                                                 *int
	InputCostPerToken, OutputCostPerToken, CachedInputCostPerToken, CacheCreationInputCostPerToken *money.Decimal
	SupportsFunctionCalling, SupportsVision, SupportsReasoning                                     *bool
	ReasoningEfforts                                                                               []string
	IsActive                                                                                       bool
}

func (n NewModelSpec) params(s db.Session, now time.Time) (InsertModelSpecParams, error) {
	var efforts []byte
	if n.ReasoningEfforts != nil {
		raw, err := json.Marshal(n.ReasoningEfforts)
		if err != nil {
			return InsertModelSpecParams{}, err
		}
		efforts = raw
	}
	opt := func(b *bool) pgtype.Bool {
		if b == nil {
			return pgtype.Bool{}
		}
		return boolean(*b)
	}
	return InsertModelSpecParams{
		ID: n.ID, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: n.CreatedBy,
		ProviderSpecID: n.ProviderSpecID, ModelName: n.ModelName, DisplayName: n.DisplayName,
		Description: text(n.Description), Kind: n.Kind, ContextWindow: int4(n.ContextWindow),
		MaxOutputTokens: int4(n.MaxOutputTokens), InputCost: priceText(n.InputCostPerToken),
		OutputCost: priceText(n.OutputCostPerToken), CachedInputCost: priceText(n.CachedInputCostPerToken),
		CacheCreationInputCost:  priceText(n.CacheCreationInputCostPerToken),
		SupportsFunctionCalling: opt(n.SupportsFunctionCalling), SupportsVision: opt(n.SupportsVision),
		SupportsReasoning: opt(n.SupportsReasoning), ReasoningEfforts: efforts, IsActive: n.IsActive,
	}, nil
}

// InsertModelSpec inserts n.
func (Specs) InsertModelSpec(ctx context.Context, s db.Session, n NewModelSpec, now time.Time) error {
	p, err := n.params(s, now)
	if err != nil {
		return err
	}
	return New(s.Q()).InsertModelSpec(ctx, p)
}

// InsertModelSpecIfAbsent inserts n unless the workspace has the model.
func (Specs) InsertModelSpecIfAbsent(ctx context.Context, s db.Session, n NewModelSpec, now time.Time) error {
	p, err := n.params(s, now)
	if err != nil {
		return err
	}
	return New(s.Q()).InsertModelSpecIfAbsent(ctx, InsertModelSpecIfAbsentParams(p))
}

// UpdateDiscoveredSpec writes the non-nil fields of d onto the spec id.
func (Specs) UpdateDiscoveredSpec(ctx context.Context, s db.Session, id uuid.UUID, d api.DiscoveredSpec, now time.Time) error {
	kind := pgtype.Text{String: d.Kind, Valid: d.Kind != ""}
	return New(s.Q()).UpdateDiscoveredSpec(ctx, UpdateDiscoveredSpecParams{
		DisplayName: pgtype.Text{String: d.DisplayName, Valid: true}, Description: text(d.Description), Kind: kind,
		ContextWindow: int4(d.ContextWindow), MaxOutputTokens: int4(d.MaxOutputTokens),
		InputCost: priceText(d.InputCostPerToken), OutputCost: priceText(d.OutputCostPerToken),
		CachedInputCost:         priceText(d.CachedInputCostPerToken),
		CacheCreationInputCost:  priceText(d.CacheCreationInputCostPerToken),
		SupportsFunctionCalling: boolean(d.SupportsFunctionCalling), SupportsVision: boolean(d.SupportsVision),
		SupportsReasoning: boolean(d.SupportsReasoning), Now: naive(now), ID: id,
	})
}

func catalogModel(r CatalogModelItemsRow) CatalogModel {
	m := CatalogModel{
		ID: r.ID, Name: r.Name, Description: fromText(r.Description), Version: fromText(r.Version), Spec: r.Spec,
		CreatedAt: fromTimestamp(r.CreatedAt), UpdatedAt: fromTimestamp(r.UpdatedAt),
		ProviderKey: fromText(r.ProviderKey), ProviderName: fromText(r.ProviderName),
	}
	if r.ProviderSpecID.Valid {
		id := r.ProviderSpecID.UUID
		m.ProviderSpecID = &id
	}
	return m
}

// CatalogModels are the llm_models items of active registries, preferred
// registry first.
func (Specs) CatalogModels(ctx context.Context, s db.Session) ([]CatalogModel, error) {
	rows, err := New(s.Q()).CatalogModelItems(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]CatalogModel, len(rows))
	for i, r := range rows {
		out[i] = catalogModel(r)
	}
	return out, nil
}

// CatalogModel is the llm_models item of an active registry with this id.
func (Specs) CatalogModel(ctx context.Context, s db.Session, id uuid.UUID) (CatalogModel, bool, error) {
	r, ok, err := one(New(s.Q()).CatalogModelItem(ctx, id))
	if !ok || err != nil {
		return CatalogModel{}, false, err
	}
	return catalogModel(CatalogModelItemsRow(r)), true, nil
}
