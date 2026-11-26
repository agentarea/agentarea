package store

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// Platform is the operator's writes of catalog rows.
type Platform struct{}

// DeclareModelSpec upserts one spec under the provider in the session's workspace.
func (Platform) DeclareModelSpec(ctx context.Context, s db.Session, providerSpecID uuid.UUID, createdBy string, m api.DeclaredModelSpec, now time.Time) (uuid.UUID, error) {
	var efforts []byte
	if m.ReasoningEfforts != nil {
		raw, err := json.Marshal(m.ReasoningEfforts)
		if err != nil {
			return uuid.Nil, err
		}
		efforts = raw
	}
	var id uuid.UUID
	err := s.Q().QueryRow(ctx, `SELECT id FROM model_specs WHERE provider_spec_id = $1 AND model_name = $2 AND workspace_id = $3`,
		providerSpecID, m.ModelName, s.Workspace().ID()).Scan(&id)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		id = uuid.New()
		description := ""
		if m.Description != nil {
			description = *m.Description
		}
		_, err = s.Q().Exec(ctx, `INSERT INTO model_specs (id, provider_spec_id, model_name, display_name, description,
			context_window, max_output_tokens, supports_vision, supports_reasoning, reasoning_efforts,
			input_cost_per_token, output_cost_per_token, cached_input_cost_per_token, cache_creation_input_cost_per_token,
			is_active, workspace_id, created_by, created_at, updated_at, kind)
			VALUES ($1, $2, $3, $4, $5, $6, $7, COALESCE($8, false), COALESCE($9, false), $10::jsonb,
			$11::text::numeric, $12::text::numeric, $13::text::numeric, $14::text::numeric, true, $15, $16, $17, $17, $18)`,
			id, providerSpecID, m.ModelName, m.DisplayName, description, m.ContextWindow, m.MaxOutputTokens,
			m.SupportsVision, m.SupportsReasoning, efforts, priceText(m.InputCostPerToken), priceText(m.OutputCostPerToken),
			priceText(m.CachedInputCostPerToken), priceText(m.CacheCreationInputCostPerToken), s.Workspace().ID(), createdBy, naive(now), kindOf(m))
		return id, err
	case err != nil:
		return uuid.Nil, err
	}
	_, err = s.Q().Exec(ctx, `UPDATE model_specs SET display_name = $2, context_window = $3, max_output_tokens = $4,
		supports_vision = COALESCE($5, supports_vision), supports_reasoning = COALESCE($6, supports_reasoning),
		reasoning_efforts = COALESCE($7::jsonb, reasoning_efforts),
		input_cost_per_token = COALESCE($8::text::numeric, input_cost_per_token),
		output_cost_per_token = COALESCE($9::text::numeric, output_cost_per_token),
		cached_input_cost_per_token = COALESCE($10::text::numeric, cached_input_cost_per_token),
		cache_creation_input_cost_per_token = COALESCE($11::text::numeric, cache_creation_input_cost_per_token),
		updated_at = $12, kind = $14 WHERE id = $1 AND workspace_id = $13`,
		id, m.DisplayName, m.ContextWindow, m.MaxOutputTokens, m.SupportsVision, m.SupportsReasoning, efforts,
		priceText(m.InputCostPerToken), priceText(m.OutputCostPerToken), priceText(m.CachedInputCostPerToken),
		priceText(m.CacheCreationInputCostPerToken), naive(now), s.Workspace().ID(), kindOf(m))
	return id, err
}

func kindOf(m api.DeclaredModelSpec) string {
	if m.Kind == "" {
		return "chat"
	}
	return m.Kind
}

// CatalogItem is the active registry item with external_id, preferred registry first.
func (Platform) CatalogItem(ctx context.Context, q db.Querier, externalID string) (uuid.UUID, map[string]any, bool, error) {
	var id uuid.UUID
	var spec map[string]any
	err := q.QueryRow(ctx, `SELECT id, spec FROM registry_items WHERE external_id = $1 AND registry_active
		ORDER BY registry_priority, id LIMIT 1`, externalID).Scan(&id, &spec)
	if errors.Is(err, pgx.ErrNoRows) {
		return uuid.Nil, nil, false, nil
	}
	if spec == nil {
		spec = map[string]any{}
	}
	return id, spec, err == nil, err
}

// DeclareMCPServer upserts the platform server in the session's workspace; changed reports a moved endpoint.
func (Platform) DeclareMCPServer(ctx context.Context, s db.Session, m api.PlatformMCPServer, slug func() (string, error), createdBy string, now time.Time) (bool, error) {
	raw, err := json.Marshal(m.JSONSpec)
	if err != nil {
		return false, err
	}
	var remoteURL *string
	var current map[string]any
	err = s.Q().QueryRow(ctx, `SELECT remote_url, json_spec FROM mcp_servers WHERE id = $1`, m.ID).Scan(&remoteURL, &current)
	if errors.Is(err, pgx.ErrNoRows) {
		sl, err := slug()
		if err != nil {
			return false, err
		}
		_, err = s.Q().Exec(ctx, `INSERT INTO mcp_servers (id, name, slug, description, version, tags, status, is_public,
			env_schema, remote_url, json_spec, registry_item_id, workspace_id, created_by, created_at, updated_at)
			VALUES ($1, $2, $3, $4, '1.0.0', '[]'::json, 'active', false, '[]'::json, $5, $6::jsonb, NULL, $7, $8, $9, $9)`,
			m.ID, m.Name, sl, m.Description, m.RemoteURL, raw, s.Workspace().ID(), createdBy, naive(now))
		return false, err
	}
	if err != nil {
		return false, err
	}
	changed := remoteURL == nil || *remoteURL != m.RemoteURL || !sameJSON(current["remotes"], m.JSONSpec["remotes"])
	_, err = s.Q().Exec(ctx, `UPDATE mcp_servers SET description = $2, remote_url = $3, json_spec = $4::jsonb,
		status = 'active', updated_by = $5, updated_at = $6
		WHERE id = $1 AND workspace_id = $7 AND (description, remote_url, json_spec, status)
		IS DISTINCT FROM ($2, $3, $4::jsonb, 'active')`,
		m.ID, m.Description, m.RemoteURL, raw, createdBy, naive(now), s.Workspace().ID())
	return changed, err
}

// MCPSlugTaken reports whether the session's workspace has a server with slug.
func (Platform) MCPSlugTaken(ctx context.Context, s db.Session, slug string) (bool, error) {
	var taken bool
	err := s.Q().QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM mcp_servers WHERE workspace_id = $1 AND slug = $2)`,
		s.Workspace().ID(), slug).Scan(&taken)
	return taken, err
}

func sameJSON(a, b any) bool {
	ra, err := json.Marshal(a)
	if err != nil {
		return false
	}
	rb, err := json.Marshal(b)
	if err != nil {
		return false
	}
	var na, nb any
	if json.Unmarshal(ra, &na) != nil || json.Unmarshal(rb, &nb) != nil {
		return false
	}
	return reflect.DeepEqual(na, nb)
}
