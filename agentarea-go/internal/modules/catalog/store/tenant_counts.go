package store

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

// ownCatalog holds for a registry of AgentArea's own catalog: the bucket every install
// reconciles, and the registries migrations made for the formerly built-in content.
const ownCatalog = `(starts_with(r.source_url, 'https://agentarea-mcp-registry.s3.amazonaws.com/registry/')
	OR starts_with(r.source_url, 'builtin://'))`

const itemSlug = `coalesce(nullif(ri.external_id, ''), ri.name)`

// TenantReads reads the catalog's tenant counts (analytics/pulse_repository.py).
type TenantReads struct{ DB db.Database }

var _ api.TenantCounter = TenantReads{}

// TenantCounts implements api.TenantCounter.
func (p TenantReads) TenantCounts(ctx context.Context, specIDs, itemIDs, providerSpecIDs []string) (api.TenantCounts, error) {
	q, release, err := p.DB.Global().Read(ctx)
	if err != nil {
		return api.TenantCounts{}, err
	}
	defer release()
	var c api.TenantCounts
	if c.SpecSlugs, err = idPairs(ctx, q, `SELECT s.id::text, `+itemSlug+` FROM mcp_servers s
		JOIN registry_items ri ON ri.id = s.registry_item_id
		JOIN registries r ON r.id = ri.registry_id
		WHERE s.id::text = ANY($1::text[]) AND `+ownCatalog, specIDs); err != nil {
		return c, err
	}
	if c.ItemSlugs, err = idPairs(ctx, q, `SELECT ri.id::text, `+itemSlug+` FROM registry_items ri
		JOIN registries r ON r.id = ri.registry_id
		WHERE ri.id::text = ANY($1::text[]) AND `+ownCatalog, itemIDs); err != nil {
		return c, err
	}
	if c.ProviderTypes, err = idPairs(ctx, q, `SELECT id::text, provider_type FROM provider_specs
		WHERE id::text = ANY($1::text[])`, providerSpecIDs); err != nil {
		return c, err
	}
	rows, err := q.Query(ctx, `SELECT b.name, EXISTS (
			SELECT 1 FROM registry_items ri JOIN registries r ON r.id = ri.registry_id
			WHERE `+ownCatalog+` AND ri.registry_type = 'bundles' AND ri.external_id = b.name), count(*)
		FROM installed_bundles b WHERE b.workspace_id <> 'platform' GROUP BY 1, 2`)
	if err != nil {
		return c, err
	}
	defer rows.Close()
	for rows.Next() {
		var b api.Bundle
		if err := rows.Scan(&b.Name, &b.Catalog, &b.Count); err != nil {
			return c, err
		}
		c.Bundles = append(c.Bundles, b)
	}
	return c, rows.Err()
}

func idPairs(ctx context.Context, q db.Querier, sql string, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := q.Query(ctx, sql, ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var k, v string
		if err := rows.Scan(&k, &v); err != nil {
			return nil, err
		}
		out[k] = v
	}
	return out, rows.Err()
}
