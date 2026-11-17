package store

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// OfferedProviderSpecs is list_specs: the provider specs offered to the
// session's workspace, at most 100, first party first then by name.
// configProviders and instanceSpecs are what models says the workspace uses.
func (Specs) OfferedProviderSpecs(ctx context.Context, s db.Session, isBuiltin *bool, configProviders, instanceSpecs []uuid.UUID) ([]api.ProviderSpec, error) {
	if configProviders == nil {
		configProviders = []uuid.UUID{}
	}
	if instanceSpecs == nil {
		instanceSpecs = []uuid.UUID{}
	}
	b := pgtype.Bool{}
	if isBuiltin != nil {
		b = boolean(*isBuiltin)
	}
	rows, err := New(s.Q()).OfferedProviderSpecs(ctx, OfferedProviderSpecsParams{
		ConfigProviders: configProviders, WorkspaceID: s.Workspace().ID(), InstanceSpecs: instanceSpecs, IsBuiltin: b,
	})
	if err != nil {
		return nil, err
	}
	out := make([]api.ProviderSpec, len(rows))
	for i, r := range rows {
		if out[i], err = providerSpec(ProviderSpecByIDRow(r)); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// ModelSpecsOfProviders are every workspace's model specs of the providers.
func (Specs) ModelSpecsOfProviders(ctx context.Context, s db.Session, ids []uuid.UUID) ([]api.ModelSpec, error) {
	rows, err := New(s.Q()).ModelSpecsOfProviders(ctx, ModelSpecsOfProvidersParams{Ids: ids, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]api.ModelSpec, len(rows))
	for i, r := range rows {
		if out[i], err = modelSpec(ModelSpecsByIDsRow(r)); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// SpecFilter narrows the workspace's model specs; nil is no filter.
type SpecFilter struct {
	ProviderSpecID *uuid.UUID
	IsActive       *bool
	Kind           *string
}

// OwnModelSpecs are the session's workspace's model specs, newest first.
func (Specs) OwnModelSpecs(ctx context.Context, s db.Session, f SpecFilter) ([]api.ModelSpec, error) {
	p := OwnModelSpecsParams{WorkspaceID: s.Workspace().ID(), Kind: text(f.Kind)}
	if f.ProviderSpecID != nil {
		p.ProviderSpecID = uuid.NullUUID{UUID: *f.ProviderSpecID, Valid: true}
	}
	if f.IsActive != nil {
		p.IsActive = boolean(*f.IsActive)
	}
	rows, err := New(s.Q()).OwnModelSpecs(ctx, p)
	if err != nil {
		return nil, err
	}
	out := make([]api.ModelSpec, len(rows))
	for i, r := range rows {
		if out[i], err = modelSpec(ModelSpecsByIDsRow(r)); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// OwnModelSpec is the session's workspace's spec with this id.
func (Specs) OwnModelSpec(ctx context.Context, s db.Session, id uuid.UUID) (api.ModelSpec, bool, error) {
	r, ok, err := one(New(s.Q()).OwnModelSpec(ctx, OwnModelSpecParams{ID: id, WorkspaceID: s.Workspace().ID()}))
	if !ok || err != nil {
		return api.ModelSpec{}, false, err
	}
	m, err := modelSpec(ModelSpecsByIDsRow(r))
	return m, err == nil, err
}

// ModelKey is a spec's (provider_spec_id, model_name).
type ModelKey struct {
	ProviderSpecID uuid.UUID
	ModelName      string
}

// OwnModelKeys are the keys the session's workspace has a spec for.
func (Specs) OwnModelKeys(ctx context.Context, s db.Session) (map[ModelKey]bool, error) {
	rows, err := New(s.Q()).OwnModelKeys(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make(map[ModelKey]bool, len(rows))
	for _, r := range rows {
		out[ModelKey(r)] = true
	}
	return out, nil
}

// SpecFields are a model spec's writable fields; nil is unset.
type SpecFields struct {
	DisplayName                    *string
	Description                    *string
	Kind                           *string
	ContextWindow, MaxOutputTokens *int
	InputCostPerToken              *money.Decimal
	OutputCostPerToken             *money.Decimal
	CachedInputCostPerToken        *money.Decimal
	CacheCreationInputCostPerToken *money.Decimal
	DefaultContextStrategy         *string
	IsActive                       *bool
}

// CreateModelSpec inserts a spec into the session's workspace with the
// model's defaults for what f leaves unset.
func (Specs) CreateModelSpec(ctx context.Context, s db.Session, id, providerSpecID uuid.UUID, createdBy, modelName string, f SpecFields, now time.Time) error {
	p := CreateModelSpecParams{
		ID: id, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, ProviderSpecID: providerSpecID,
		ModelName: modelName, Description: text(f.Description), ContextWindow: int4(f.ContextWindow),
		MaxOutputTokens: int4(f.MaxOutputTokens), InputCost: priceText(f.InputCostPerToken),
		OutputCost: priceText(f.OutputCostPerToken), CachedInputCost: priceText(f.CachedInputCostPerToken),
		CacheCreationInputCost: priceText(f.CacheCreationInputCostPerToken),
		DefaultContextStrategy: text(f.DefaultContextStrategy), IsActive: true, Kind: "chat",
	}
	if f.DisplayName != nil {
		p.DisplayName = *f.DisplayName
	}
	if f.Kind != nil {
		p.Kind = *f.Kind
	}
	if f.IsActive != nil {
		p.IsActive = *f.IsActive
	}
	return New(s.Q()).CreateModelSpec(ctx, p)
}

// UpdateModelSpec writes f's set fields onto the workspace's spec id;
// updated_at moves only when touch. False when no such spec.
func (Specs) UpdateModelSpec(ctx context.Context, s db.Session, id uuid.UUID, f SpecFields, touch bool, now time.Time) (bool, error) {
	p := UpdateModelSpecParams{
		DisplayName: text(f.DisplayName), Description: text(f.Description), Kind: text(f.Kind),
		ContextWindow: int4(f.ContextWindow), MaxOutputTokens: int4(f.MaxOutputTokens),
		InputCost: priceText(f.InputCostPerToken), OutputCost: priceText(f.OutputCostPerToken),
		CachedInputCost: priceText(f.CachedInputCostPerToken), CacheCreationInputCost: priceText(f.CacheCreationInputCostPerToken),
		DefaultContextStrategy: text(f.DefaultContextStrategy), Touch: touch, Now: naive(now),
		ID: id, WorkspaceID: s.Workspace().ID(),
	}
	if f.IsActive != nil {
		p.IsActive = boolean(*f.IsActive)
	}
	n, err := New(s.Q()).UpdateModelSpec(ctx, p)
	return n > 0, err
}

// DeleteModelSpec removes the workspace's spec id; its instances go with it.
func (Specs) DeleteModelSpec(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteOwnModelSpec(ctx, DeleteOwnModelSpecParams{ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}
