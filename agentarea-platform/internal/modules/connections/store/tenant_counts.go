package store

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
)

// TenantReads reads connections' tenant counts (analytics/pulse_repository.py).
type TenantReads struct{ DB db.Database }

var _ api.TenantCounter = TenantReads{}

// TenantCounts implements api.TenantCounter.
func (p TenantReads) TenantCounts(ctx context.Context) (api.TenantCounts, error) {
	q, release, err := p.DB.Global().Read(ctx)
	if err != nil {
		return api.TenantCounts{}, err
	}
	defer release()
	var c api.TenantCounts
	if c.MCP, err = db.CountOne(ctx, q, `SELECT count(*) FROM mcp_server_instances WHERE workspace_id <> 'platform'`); err != nil {
		return c, err
	}
	if c.OpenAPI, err = db.CountOne(ctx, q, `SELECT count(*) FROM openapi_connections WHERE workspace_id <> 'platform'`); err != nil {
		return c, err
	}
	if c.MCPBySpec, err = connectorCounts(ctx, q, `SELECT i.server_spec_id, coalesce(a.auth_type, 'none'), count(*)
		FROM mcp_server_instances i LEFT JOIN mcp_auth_configs a ON a.id = i.auth_config_id
		WHERE i.workspace_id <> 'platform' GROUP BY 1, 2`); err != nil {
		return c, err
	}
	if c.OpenAPIByItem, err = connectorCounts(ctx, q, `SELECT coalesce(o.registry_item_id::text, ''), coalesce(a.auth_type, 'none'), count(*)
		FROM openapi_connections o LEFT JOIN mcp_auth_configs a ON a.id = o.auth_config_id
		WHERE o.workspace_id <> 'platform' GROUP BY 1, 2`); err != nil {
		return c, err
	}
	c.MCPByVerification, err = db.CountBy(ctx, q, `SELECT coalesce(verification ->> 'status', 'unknown'), count(*)
		FROM mcp_server_instances WHERE workspace_id <> 'platform' GROUP BY 1`)
	return c, err
}

func connectorCounts(ctx context.Context, q db.Querier, sql string) ([]api.Connectors, error) {
	rows, err := q.Query(ctx, sql)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []api.Connectors
	for rows.Next() {
		var c api.Connectors
		var n int64
		if err := rows.Scan(&c.Source, &c.AuthType, &n); err != nil {
			return nil, err
		}
		c.Count = int(n)
		out = append(out, c)
	}
	return out, rows.Err()
}
