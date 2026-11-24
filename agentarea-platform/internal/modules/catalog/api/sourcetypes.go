package api

import (
	"context"
	"encoding/json"
)

// SourceTypeRow is one source-type entry of the catalog: its slug (external_id) and whole spec.
type SourceTypeRow struct {
	Slug string
	Spec json.RawMessage
}

// SourceTypes reads the global catalog's source types (registry_items of type source_types,
// active registries only), as CatalogSourceTypeRepository does; the caller parses the entries.
type SourceTypes interface {
	// SourceTypeRows orders by registry priority, recommendation rank, then name.
	SourceTypeRows(ctx context.Context) ([]SourceTypeRow, error)
	// SourceTypeRowsBySlug is the rows of one slug, by registry priority.
	SourceTypeRowsBySlug(ctx context.Context, slug string) ([]SourceTypeRow, error)
}
