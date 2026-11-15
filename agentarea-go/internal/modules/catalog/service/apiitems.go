package service

import (
	"bytes"
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

var _ api.APIItems = (*Service)(nil)

// APIItem is load_catalog_api_item.
func (s *Service) APIItem(ctx context.Context, ws scope.Workspace, id string) (api.APIItem, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return api.APIItem{}, err
	}
	defer release()
	it, ok, err := s.d.Registries.GetItem(ctx, sess, id)
	if err != nil {
		return api.APIItem{}, err
	}
	if !ok {
		return api.APIItem{}, api.ErrAPIItemNotFound
	}
	spec := map[string]any{}
	if len(it.Spec) > 0 && !bytes.Equal(it.Spec, []byte("null")) {
		dec := json.NewDecoder(bytes.NewReader(it.Spec))
		dec.UseNumber()
		var v any
		if err := dec.Decode(&v); err != nil {
			return api.APIItem{}, err
		}
		if m, isObj := v.(map[string]any); isObj {
			spec = m
		}
	}
	r, ok, err := s.d.Registries.Get(ctx, sess, it.RegistryID)
	if err != nil {
		return api.APIItem{}, err
	}
	if !ok || !r.IsActive || r.RegistryType != "mcp_servers" || spec["connection_type"] != "openapi" {
		return api.APIItem{}, api.ErrNotAPIItem
	}
	return api.APIItem{ID: it.ID, Name: it.Name, Description: it.Description, Spec: spec}, nil
}
