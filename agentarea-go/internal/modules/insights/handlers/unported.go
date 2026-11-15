package handlers

import (
	"context"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/insights"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/service"
)

// unported answers the operations never mounted from the strict server:
// GET /health is the serve edge's root route, and PUT /settings is putSettings.
type unported struct{}

func (unported) HealthHealthGet(context.Context, gen.HealthHealthGetRequestObject) (gen.HealthHealthGetResponseObject, error) {
	return nil, service.ErrNotPorted
}

func (unported) UpdateWorkspaceSettingsV1SettingsPut(context.Context, gen.UpdateWorkspaceSettingsV1SettingsPutRequestObject) (gen.UpdateWorkspaceSettingsV1SettingsPutResponseObject, error) {
	return nil, service.ErrNotPorted
}
