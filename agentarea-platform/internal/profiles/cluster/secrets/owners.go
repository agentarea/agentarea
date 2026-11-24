package secrets

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// ownerTables maps an owner type the catalog surfaces to the table holding it
// (api/v1/_secret_owners.py). Anything else is machine-generated and never
// reaches a page.
func ownerTables() map[string]string {
	return map[string]string{
		"provider_config":    "provider_configs",
		"mcp_instance":       "mcp_server_instances",
		"mcp_auth_config":    "mcp_auth_configs",
		"openapi_connection": "openapi_connections",
		"trigger":            "triggers",
		"agent":              "agents",
	}
}

// OwnerKey is the owner a secret row names.
type OwnerKey struct {
	Type string
	ID   string
}

// ResolveOwnerNames maps owners to display names with one query per owner
// type, omitting owners that are gone: a secret can outlive the connection
// that minted it, and a missing entry says so better than an invented name.
// The table comes from the fixed map, never from input.
func ResolveOwnerNames(ctx context.Context, s db.Session, owners []OwnerKey) (map[OwnerKey]string, error) {
	tables := ownerTables()
	byType := map[string]map[string]struct{}{}
	for _, o := range owners {
		if _, ok := tables[o.Type]; !ok {
			continue
		}
		if _, err := uuid.Parse(o.ID); err != nil {
			continue
		}
		if byType[o.Type] == nil {
			byType[o.Type] = map[string]struct{}{}
		}
		byType[o.Type][o.ID] = struct{}{}
	}
	out := map[OwnerKey]string{}
	for typ, set := range byType {
		ids := make([]string, 0, len(set))
		for id := range set {
			ids = append(ids, id)
		}
		rows, err := s.Q().Query(ctx,
			fmt.Sprintf(`SELECT id::text, name FROM %s WHERE id = ANY($1::uuid[]) AND workspace_id = $2`, tables[typ]), //nolint:gosec // table from a fixed map
			ids, s.Workspace().ID())
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				rows.Close()
				return nil, err
			}
			out[OwnerKey{typ, id}] = name
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	return out, nil
}
