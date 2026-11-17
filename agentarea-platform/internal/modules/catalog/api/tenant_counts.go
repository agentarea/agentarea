package api

import "context"

// Bundle is a count of tenant installed bundles of one name.
type Bundle struct {
	Name string
	// Catalog holds when AgentArea's own catalog has a bundle of that name.
	Catalog bool
	Count   int
}

// TenantCounts are the catalog's reads over given ids. Only items of AgentArea's own catalog
// (the S3 registry and the formerly built-in content) have a slug; an operator's registry has none.
type TenantCounts struct {
	// SpecSlugs are the given MCP server spec ids of AgentArea's catalog by slug.
	SpecSlugs map[string]string
	// ItemSlugs are the given registry item ids of AgentArea's catalog by slug.
	ItemSlugs map[string]string
	// ProviderTypes are the given provider spec ids by provider type.
	ProviderTypes map[string]string
	Bundles       []Bundle
}

// TenantCounter is analytics/pulse_repository.py's catalog_slug, catalog_bundle and the llm_providers join.
type TenantCounter interface {
	TenantCounts(ctx context.Context, specIDs, itemIDs, providerSpecIDs []string) (TenantCounts, error)
}
