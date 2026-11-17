package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
)

// Platform is the operator's writes of platform connections.
type Platform struct{}

// DeclareMCP upserts the instance in the session's workspace. verification, when set, replaces the
// row's and clears its tools.
func (Platform) DeclareMCP(ctx context.Context, s db.Session, d api.DeclaredMCP, jsonSpec, verification []byte, createdBy string, now time.Time) error {
	var exists bool
	if err := s.Q().QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM mcp_server_instances WHERE id = $1)`, d.InstanceID).Scan(&exists); err != nil {
		return err
	}
	ws := s.Workspace().ID()
	if !exists {
		_, err := s.Q().Exec(ctx, `INSERT INTO mcp_server_instances (id, server_spec_id, name, description, transport,
			json_spec, network_scope, managed_by, workspace_id, created_by, created_at, updated_at)
			VALUES ($1, $2, $3, $4, 'url', $5::jsonb, 'private', 'platform', $6, $7, $8, $8)`,
			d.InstanceID, d.ServerID, d.Name, d.Description, jsonSpec, ws, createdBy, naive(now))
		return err
	}
	if verification != nil {
		_, err := s.Q().Exec(ctx, `UPDATE mcp_server_instances SET server_spec_id = $2, name = $3, description = $4,
			transport = 'url', json_spec = $5::jsonb, managed_by = 'platform', verification = $6::jsonb, tools = NULL,
			updated_at = $7 WHERE id = $1 AND workspace_id = $8`,
			d.InstanceID, d.ServerID, d.Name, d.Description, jsonSpec, verification, naive(now), ws)
		return err
	}
	_, err := s.Q().Exec(ctx, `UPDATE mcp_server_instances SET server_spec_id = $2, name = $3, description = $4,
		transport = 'url', json_spec = $5::jsonb, managed_by = 'platform', updated_at = $6
		WHERE id = $1 AND workspace_id = $7 AND (server_spec_id, name, description, transport, json_spec, managed_by)
		IS DISTINCT FROM ($2, $3, $4, 'url', $5::jsonb, 'platform')`,
		d.InstanceID, d.ServerID, d.Name, d.Description, jsonSpec, naive(now), ws)
	return err
}

// DeclareOpenAPI upserts the connection in the session's workspace.
func (Platform) DeclareOpenAPI(ctx context.Context, s db.Session, d api.DeclaredOpenAPI, spec, tools, headers []byte, createdBy string, now time.Time) error {
	ws := s.Workspace().ID()
	var id uuid.UUID
	err := s.Q().QueryRow(ctx, `SELECT id FROM openapi_connections WHERE id = $1`, d.ID).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		_, err = s.Q().Exec(ctx, `INSERT INTO openapi_connections (id, name, description, spec_url, spec_content, base_url,
			registry_item_id, available_tools, custom_headers, allowed_auth_origins, status, managed_by, workspace_id,
			created_by, created_at, updated_at)
			VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8::jsonb, $9::json, NULL, 'active', 'platform', $10, $11, $12, $12)`,
			d.ID, d.Name, d.Description, d.SpecURL, spec, d.BaseURL, d.RegistryItemID, tools, headers, ws, createdBy, naive(now))
		return err
	}
	if err != nil {
		return err
	}
	_, err = s.Q().Exec(ctx, `UPDATE openapi_connections SET name = $2, description = $3, spec_url = $4,
		spec_content = $5::jsonb, base_url = $6, registry_item_id = $7, available_tools = $8::jsonb,
		custom_headers = $9::json, allowed_auth_origins = NULL, status = 'active', managed_by = 'platform', updated_at = $10
		WHERE id = $1 AND workspace_id = $11 AND (name, description, spec_url, spec_content, base_url, registry_item_id,
		available_tools, custom_headers::jsonb, allowed_auth_origins::jsonb, status, managed_by)
		IS DISTINCT FROM ($2, $3, $4, $5::jsonb, $6, $7, $8::jsonb, $9::jsonb, NULL::jsonb, 'active', 'platform')`,
		d.ID, d.Name, d.Description, d.SpecURL, spec, d.BaseURL, d.RegistryItemID, tools, headers, naive(now), ws)
	return err
}
