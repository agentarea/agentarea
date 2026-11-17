package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

// Platform is the operator's writes of provider configurations and model instances.
type Platform struct{}

// DeclareConfig upserts the configuration by id in the session's workspace.
func (Platform) DeclareConfig(ctx context.Context, s db.Session, d api.ProviderDeclaration, secretName, secretID, createdBy string, now time.Time) error {
	var managedBy *string
	if d.PlatformManaged {
		v := "platform"
		managedBy = &v
	}
	tag, err := s.Q().Exec(ctx, `UPDATE provider_configs SET name = $2, api_key = $3, api_key_secret_id = $4,
		endpoint_url = $5, managed_by = $6, is_active = true, is_public = $7, updated_at = $8 WHERE id = $1`,
		d.ConfigID, d.Name, secretName, secretID, d.EndpointURL, managedBy, d.IsPublic, naive(now))
	if err != nil || tag.RowsAffected() > 0 {
		return err
	}
	_, err = s.Q().Exec(ctx, `INSERT INTO provider_configs (id, provider_spec_id, name, api_key, api_key_secret_id,
		endpoint_url, managed_by, is_active, is_public, workspace_id, created_by, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8, $9, $10, $11, $11)`,
		d.ConfigID, d.ProviderSpecID, d.Name, secretName, secretID, d.EndpointURL, managedBy, d.IsPublic,
		s.Workspace().ID(), createdBy, naive(now))
	return err
}

// DeclareInstance creates the instance unless the configuration already has one of the spec, then
// sets its tags when given.
func (Platform) DeclareInstance(ctx context.Context, s db.Session, configID uuid.UUID, in api.DeclaredInstance, createdBy string, now time.Time) error {
	var existing uuid.UUID
	err := s.Q().QueryRow(ctx, `SELECT id FROM model_instances WHERE id = $1 OR (provider_config_id = $2 AND model_spec_id = $3) LIMIT 1`,
		in.ID, configID, in.ModelSpecID).Scan(&existing)
	if errors.Is(err, pgx.ErrNoRows) {
		tags := in.Tags
		if tags == nil {
			tags = []string{}
		}
		raw, err := json.Marshal(tags)
		if err != nil {
			return err
		}
		_, err = s.Q().Exec(ctx, `INSERT INTO model_instances (id, provider_config_id, model_spec_id, name, is_active,
			is_public, tags, workspace_id, created_by, created_at, updated_at)
			VALUES ($1, $2, $3, $4, true, true, $5::jsonb, $6, $7, $8, $8)`,
			in.ID, configID, in.ModelSpecID, in.Name, raw, s.Workspace().ID(), createdBy, naive(now))
		return err
	}
	if err != nil || in.Tags == nil {
		return err
	}
	raw, err := json.Marshal(in.Tags)
	if err != nil {
		return err
	}
	_, err = s.Q().Exec(ctx, `UPDATE model_instances SET tags = $2::jsonb, updated_at = $3 WHERE id = $1 AND workspace_id = $4`,
		existing, raw, naive(now), s.Workspace().ID())
	return err
}

// PlatformDefaults is the name of every active platform-managed instance tagged default, by name.
func (Platform) PlatformDefaults(ctx context.Context, q db.Querier) ([]string, error) {
	rows, err := q.Query(ctx, `SELECT mi.name FROM model_instances mi JOIN provider_configs pc ON pc.id = mi.provider_config_id
		WHERE pc.managed_by = 'platform' AND mi.is_active AND mi.tags @> '["default"]'::jsonb ORDER BY mi.name`)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}
