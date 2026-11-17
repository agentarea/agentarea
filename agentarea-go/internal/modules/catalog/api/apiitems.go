package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// APIItem is a one-click API catalog item (CatalogApiItem).
type APIItem struct {
	ID string
	// ExternalID is the catalog id billing and caps know a connection made from it by.
	ExternalID  string
	Name        string
	Description *string
	// Spec is the item's spec, numbers kept as written (json.Number).
	Spec map[string]any
}

// Errors of APIItems.APIItem; their texts are Python's.
var (
	ErrAPIItemNotFound = errors.New("Catalog connection not found")                   //nolint:staticcheck // Python's detail
	ErrNotAPIItem      = errors.New("Catalog item is not a one-click API connection") //nolint:staticcheck // Python's detail
)

// APIItems is what connections reads of one-click API catalog items.
type APIItems interface {
	// APIItem is load_catalog_api_item: ErrAPIItemNotFound when no item has
	// the id, ErrNotAPIItem unless it is an openapi item of an active
	// mcp_servers registry.
	APIItem(ctx context.Context, ws scope.Workspace, id string) (APIItem, error)
}
