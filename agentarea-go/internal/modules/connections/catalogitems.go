package connections

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// catalogItems is service.CatalogItems over catalog's APIItems.
type catalogItems struct{ items catalogapi.APIItems }

func (c catalogItems) CatalogAPIItem(ctx context.Context, ws scope.Workspace, id uuid.UUID) (service.CatalogAPIItem, error) {
	it, err := c.items.APIItem(ctx, ws, id.String())
	switch {
	case errors.Is(err, catalogapi.ErrAPIItemNotFound):
		return service.CatalogAPIItem{}, &domain.NotFound{Msg: err.Error()}
	case errors.Is(err, catalogapi.ErrNotAPIItem):
		return service.CatalogAPIItem{}, &domain.Invalid{Msg: err.Error()}
	case err != nil:
		return service.CatalogAPIItem{}, err
	}
	parsed, err := uuid.Parse(it.ID)
	if err != nil {
		return service.CatalogAPIItem{}, err
	}
	return service.CatalogAPIItem{ID: parsed, Name: it.Name, Description: it.Description, Spec: it.Spec}, nil
}
