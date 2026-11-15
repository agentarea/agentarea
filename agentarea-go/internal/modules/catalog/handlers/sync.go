package handlers

import (
	"context"
	"errors"
	"net/http"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/catalog"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
)

// WorkspaceSyncScope is the workspace-registry sync's rate-limit bucket:
// one sync a minute per workspace.
const WorkspaceSyncScope = "workspace-registry-sync"

func syncJSON(st service.SyncStats) wirejson.Object {
	items := make([]any, len(st.SkippedItems))
	for i, it := range st.SkippedItems {
		items[i] = wirejson.Object{{Key: "external_id", Value: it.ExternalID}, {Key: "reason", Value: it.Reason}}
	}
	return wirejson.Object{
		{Key: "new_specs", Value: st.NewSpecs},
		{Key: "updates_flagged", Value: st.UpdatesFlagged},
		{Key: "unchanged", Value: st.Unchanged},
		{Key: "total", Value: st.Total},
		{Key: "skipped", Value: st.Skipped},
		{Key: "skipped_items", Value: items},
	}
}

func syncFailed(err error) error {
	var se *service.SyncError
	if errors.As(err, &se) {
		return httpx.HTTPError(http.StatusBadGateway, "Sync failed: "+se.Msg)
	}
	return err
}

func (s *Server) SyncRegistryV1RegistriesRegistryIdSyncPost(ctx context.Context, rq gen.SyncRegistryV1RegistriesRegistryIdSyncPostRequestObject) (gen.SyncRegistryV1RegistriesRegistryIdSyncPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if _, found, err := s.svc.PlatformRegistry(ctx, c.Workspace, rq.RegistryId.String()); err != nil {
		return nil, err
	} else if !found {
		return nil, service.ErrRegistryNotFound()
	}
	st, err := s.svc.SyncRegistry(ctx, rq.RegistryId.String(), false)
	if err != nil {
		return nil, syncFailed(err)
	}
	return ok(syncJSON(st)), nil
}

func (s *Server) SyncWorkspaceRegistryV1WorkspaceRegistriesRegistryIdSyncPost(ctx context.Context, rq gen.SyncWorkspaceRegistryV1WorkspaceRegistriesRegistryIdSyncPostRequestObject) (gen.SyncWorkspaceRegistryV1WorkspaceRegistriesRegistryIdSyncPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if _, found, err := s.svc.WorkspaceRegistry(ctx, c.Workspace, rq.RegistryId.String()); err != nil {
		return nil, err
	} else if !found {
		return nil, service.ErrRegistryNotFound()
	}
	if err := httpx.EnforceRateLimit(ctx, s.rate, s.log, WorkspaceSyncScope, c.Workspace.ID(), 1); err != nil {
		return nil, err
	}
	st, err := s.svc.SyncRegistry(ctx, rq.RegistryId.String(), inputFrom(ctx).force)
	if err != nil {
		return nil, syncFailed(err)
	}
	return ok(syncJSON(st)), nil
}

func (s *Server) DeleteWorkspaceRegistryV1WorkspaceRegistriesRegistryIdDelete(ctx context.Context, rq gen.DeleteWorkspaceRegistryV1WorkspaceRegistriesRegistryIdDeleteRequestObject) (gen.DeleteWorkspaceRegistryV1WorkspaceRegistriesRegistryIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if _, found, err := s.svc.WorkspaceRegistry(ctx, c.Workspace, rq.RegistryId.String()); err != nil {
		return nil, err
	} else if !found {
		return nil, service.ErrRegistryNotFound()
	}
	status, kept, err := s.svc.RemoveWorkspaceRegistry(ctx, c, rq.RegistryId.String())
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "status", Value: status}, {Key: "kept_items", Value: kept}}), nil
}
