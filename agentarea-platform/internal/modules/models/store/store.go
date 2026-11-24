package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

//go:generate sqlc generate

// Store reads and writes provider configurations and model instances inside
// the session's workspace; reads widen to the platform's rows, writes do not.
type Store struct{}

func text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func fromText(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	s := t.String
	return &s
}

func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.Truncate(time.Microsecond), Valid: true}
}

func nullUUID(p *string) (uuid.NullUUID, error) {
	if p == nil {
		return uuid.NullUUID{}, nil
	}
	u, err := uuid.Parse(*p)
	if err != nil {
		return uuid.NullUUID{}, err
	}
	return uuid.NullUUID{UUID: u, Valid: true}, nil
}

func config(r ProviderConfig) domain.Config {
	c := domain.Config{
		ID: r.ID.String(), ProviderSpecID: r.ProviderSpecID.String(), Name: r.Name, Description: fromText(r.Description),
		APIKey: fromText(r.ApiKey), EndpointURL: fromText(r.EndpointUrl), IsActive: r.IsActive, IsPublic: r.IsPublic,
		WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, CreatedAt: r.CreatedAt.Time, UpdatedAt: r.UpdatedAt.Time,
		ManagedBy: fromText(r.ManagedBy),
	}
	if r.ApiKeySecretID.Valid {
		s := r.ApiKeySecretID.UUID.String()
		c.APIKeySecretID = &s
	}
	return c
}

func instance(r ModelInstance) domain.Instance {
	in := domain.Instance{
		ID: r.ID.String(), ProviderConfigID: r.ProviderConfigID.String(), ModelSpecID: r.ModelSpecID.String(),
		Name: r.Name, Description: fromText(r.Description), IsActive: r.IsActive, IsPublic: r.IsPublic,
		WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, CreatedAt: r.CreatedAt.Time, UpdatedAt: r.UpdatedAt.Time,
		Tags: []string{},
	}
	_ = json.Unmarshal(r.Tags, &in.Tags)
	if in.Tags == nil {
		in.Tags = []string{}
	}
	return in
}

// Config is a configuration the workspace may read (its own or the platform's).
func (Store) Config(ctx context.Context, s db.Session, id uuid.UUID) (domain.Config, bool, error) {
	r, err := New(s.Q()).GetConfig(ctx, GetConfigParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Config{}, false, nil
	}
	if err != nil {
		return domain.Config{}, false, err
	}
	return config(r), true, nil
}

// ErrLockBusy is a configuration row another transaction held past the lock timeout.
var ErrLockBusy = errors.New("the provider configuration is locked by another call")

// LockConfig holds the workspace's own configuration row for the rest of the
// session's transaction, waiting at most the lock timeout (ErrLockBusy);
// false when it has no such row.
func (Store) LockConfig(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	q := New(s.Q())
	if err := q.SetLockTimeout(ctx); err != nil {
		return false, err
	}
	_, err := q.LockOwnConfig(ctx, LockOwnConfigParams{ID: id, WorkspaceID: s.Workspace().ID()})
	var pg *pgconn.PgError
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return false, nil
	case errors.As(err, &pg) && pg.Code == "55P03":
		return false, ErrLockBusy
	}
	return err == nil, err
}

// ConfigFilter narrows a configuration listing.
type ConfigFilter struct {
	ProviderSpecID *uuid.UUID
	IsActive       *bool
}

// Configs is list_configs: the newest 100 visible, newest first.
func (Store) Configs(ctx context.Context, s db.Session, f ConfigFilter) ([]domain.Config, error) {
	q := New(s.Q())
	p := ListConfigIDsParams{WorkspaceID: s.Workspace().ID()}
	if f.ProviderSpecID != nil {
		p.BySpec, p.ProviderSpecID = true, *f.ProviderSpecID
	}
	if f.IsActive != nil {
		p.ByActive, p.IsActive = true, *f.IsActive
	}
	ids, err := q.ListConfigIDs(ctx, p)
	if err != nil || len(ids) == 0 {
		return []domain.Config{}, err
	}
	rows, err := q.ConfigsByIDs(ctx, ConfigsByIDsParams{Ids: ids, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Config, len(rows))
	for i, r := range rows {
		out[i] = config(r)
	}
	return out, nil
}

// InstanceSpecIDs is the model_spec_id of each configuration's instances in the session's workspace.
func (Store) InstanceSpecIDs(ctx context.Context, s db.Session, configIDs []uuid.UUID) (map[string][]string, error) {
	out := map[string][]string{}
	if len(configIDs) == 0 {
		return out, nil
	}
	rows, err := New(s.Q()).InstanceSpecsOfConfigs(ctx, InstanceSpecsOfConfigsParams{Ids: configIDs, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		k := r.ProviderConfigID.String()
		out[k] = append(out[k], r.ModelSpecID.String())
	}
	return out, nil
}

// OwnsConfig: the configuration is this workspace's own (strict filter).
func (Store) OwnsConfig(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).OwnsConfig(ctx, OwnsConfigParams{ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}

// InsertConfig writes a configuration of the session's workspace.
func (Store) InsertConfig(ctx context.Context, s db.Session, c domain.Config, now time.Time) error {
	id, err := uuid.Parse(c.ID)
	if err != nil {
		return err
	}
	spec, err := uuid.Parse(c.ProviderSpecID)
	if err != nil {
		return err
	}
	secret, err := nullUUID(c.APIKeySecretID)
	if err != nil {
		return err
	}
	return New(s.Q()).InsertConfig(ctx, InsertConfigParams{
		ID: id, ProviderSpecID: spec, Name: c.Name, Description: text(c.Description), ApiKey: text(c.APIKey),
		EndpointUrl: text(c.EndpointURL), IsActive: c.IsActive, IsPublic: c.IsPublic,
		WorkspaceID: s.Workspace().ID(), CreatedBy: c.CreatedBy, Now: naive(now), ApiKeySecretID: secret,
	})
}

// UpdateConfig writes c's mutable fields; false when the row is not this workspace's.
func (Store) UpdateConfig(ctx context.Context, s db.Session, c domain.Config, now time.Time) (bool, error) {
	id, err := uuid.Parse(c.ID)
	if err != nil {
		return false, err
	}
	secret, err := nullUUID(c.APIKeySecretID)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).UpdateConfig(ctx, UpdateConfigParams{
		ID: id, WorkspaceID: s.Workspace().ID(), Name: c.Name, Description: text(c.Description), ApiKey: text(c.APIKey),
		EndpointUrl: text(c.EndpointURL), IsActive: c.IsActive, IsPublic: c.IsPublic, ApiKeySecretID: secret, Now: naive(now),
	})
	return n > 0, err
}

// DeleteConfig removes one of this workspace's own configurations.
func (Store) DeleteConfig(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteConfig(ctx, DeleteConfigParams{ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}

// ProviderSpecIDsWithVisibleConfigs are the specs of the configurations the workspace reads.
func (Store) ProviderSpecIDsWithVisibleConfigs(ctx context.Context, s db.Session) ([]uuid.UUID, error) {
	return New(s.Q()).ProviderSpecIDsWithVisibleConfigs(ctx, s.Workspace().ID())
}

// Instance is an instance the workspace may read (its own or one on a platform configuration).
func (Store) Instance(ctx context.Context, s db.Session, id uuid.UUID) (domain.Instance, bool, error) {
	r, err := New(s.Q()).GetInstance(ctx, GetInstanceParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Instance{}, false, nil
	}
	if err != nil {
		return domain.Instance{}, false, err
	}
	return instance(r), true, nil
}

// InstanceFilter narrows an instance listing; IDs non-nil restricts to them.
type InstanceFilter struct {
	ProviderConfigID, ModelSpecID *uuid.UUID
	IsActive                      *bool
	IDs                           []uuid.UUID
	ByIDs                         bool
}

// Instances is list_instances: the newest 100 visible, newest first.
func (Store) Instances(ctx context.Context, s db.Session, f InstanceFilter) ([]domain.Instance, error) {
	q := New(s.Q())
	p := ListInstanceIDsParams{WorkspaceID: s.Workspace().ID(), ByIds: f.ByIDs, Ids: f.IDs}
	if p.Ids == nil {
		p.Ids = []uuid.UUID{}
	}
	if f.ProviderConfigID != nil {
		p.ByConfig, p.ProviderConfigID = true, *f.ProviderConfigID
	}
	if f.ModelSpecID != nil {
		p.BySpec, p.ModelSpecID = true, *f.ModelSpecID
	}
	if f.IsActive != nil {
		p.ByActive, p.IsActive = true, *f.IsActive
	}
	ids, err := q.ListInstanceIDs(ctx, p)
	if err != nil || len(ids) == 0 {
		return []domain.Instance{}, err
	}
	rows, err := q.InstancesByIDs(ctx, InstancesByIDsParams{Ids: ids, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Instance, len(rows))
	for i, r := range rows {
		out[i] = instance(r)
	}
	return out, nil
}

// VisibleInstanceSpecs maps each visible instance id to its model spec id.
func (Store) VisibleInstanceSpecs(ctx context.Context, s db.Session) (map[uuid.UUID]uuid.UUID, error) {
	rows, err := New(s.Q()).VisibleInstanceSpecs(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]uuid.UUID, len(rows))
	for _, r := range rows {
		out[r.ID] = r.ModelSpecID
	}
	return out, nil
}

// ConfigsOfInstances are the configurations instances run on, by id, whichever workspace holds them.
func (Store) ConfigsOfInstances(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]domain.Config, error) {
	out := map[string]domain.Config{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := New(s.Q()).ConfigsOfInstances(ctx, ids)
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		out[r.ID.String()] = config(r)
	}
	return out, nil
}

// InsertInstance writes an instance of the session's workspace.
func (Store) InsertInstance(ctx context.Context, s db.Session, in domain.Instance, now time.Time) error {
	id, err := uuid.Parse(in.ID)
	if err != nil {
		return err
	}
	cfg, err := uuid.Parse(in.ProviderConfigID)
	if err != nil {
		return err
	}
	spec, err := uuid.Parse(in.ModelSpecID)
	if err != nil {
		return err
	}
	return New(s.Q()).InsertInstance(ctx, InsertInstanceParams{
		ID: id, ProviderConfigID: cfg, ModelSpecID: spec, Name: in.Name, Description: text(in.Description),
		IsActive: in.IsActive, IsPublic: in.IsPublic, WorkspaceID: s.Workspace().ID(), CreatedBy: in.CreatedBy, Now: naive(now),
	})
}

// DeleteInstance removes one of this workspace's own instances.
func (Store) DeleteInstance(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteInstance(ctx, DeleteInstanceParams{ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}
