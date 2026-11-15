package service

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

func dumps(v any) ([]byte, error) { return wirejson.Marshal(v, wirejson.Dumps) }

func specObject(raw []byte) wirejson.Object {
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return wirejson.Object{}
	}
	o, _ := v.(wirejson.Object)
	if o == nil {
		return wirejson.Object{}
	}
	return o
}

// updateEntity is _update_entity as the API's RegistryService has it: an
// MCP server mirror in the caller's workspace; no provider or model spec
// repository, so LLM items refuse.
func (s *Service) updateEntity(ctx context.Context, sess db.Session, r domain.Registry, it domain.Item) error {
	switch r.RegistryType {
	case domain.TypeMCPServers:
		spec := specObject(it.Spec)
		if c, _ := spec.Get("connection_type"); c == "openapi" {
			return nil
		}
		m, err := MirrorOf(spec)
		if err != nil {
			return err
		}
		row := store.MirroredServer{RemoteURL: m.RemoteURL, DockerImageURL: m.DockerImageURL, RegistryURL: r.SourceURL}
		if it.Description != nil {
			row.Description = *it.Description
		}
		row.Version = "latest"
		if it.Version != nil && *it.Version != "" {
			row.Version = *it.Version
		}
		if row.Tags, err = dumps(m.Tags); err != nil {
			return err
		}
		if row.EnvSchema, err = dumps(m.EnvSchema); err != nil {
			return err
		}
		var cmd any
		if m.Cmd != nil {
			cmd = m.Cmd
		}
		if row.Cmd, err = dumps(cmd); err != nil {
			return err
		}
		if row.JSONSpec, err = dumps(m.JSONSpec); err != nil {
			return err
		}
		_, err = s.d.Registries.UpdateMirroredServer(ctx, sess, *it.InstalledEntityID, row, s.d.Now())
		return err
	case domain.TypeSkills, domain.TypeAgents, domain.TypeBundles, domain.TypeSourceTypes:
		return nil
	case domain.TypeLLMProviders:
		return valueErr("Provider spec repository not available")
	case domain.TypeLLMModels:
		return valueErr("Provider and model spec repositories required")
	}
	return valueErr("Unknown registry_type: %s", r.RegistryType)
}

// UpdateItemSpec is update_item_spec: re-apply the item to its installed
// entity and record its version. Refusals are ValueErrors (400).
func (s *Service) UpdateItemSpec(ctx context.Context, ws scope.Workspace, itemID string) error {
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		it, ok, err := s.d.Registries.GetItem(ctx, sess, itemID)
		if err != nil {
			return err
		}
		if !ok {
			return valueErr("Registry item %s not found", itemID)
		}
		if it.InstalledEntityID == nil {
			return valueErr("Item %s has no installed entity", it.Name)
		}
		if !it.UpdateAvailable {
			return valueErr("Item %s is already up to date", it.Name)
		}
		r, ok, err := s.d.Registries.Get(ctx, sess, it.RegistryID)
		if err != nil {
			return err
		}
		if !ok {
			return valueErr("Registry %s not found", it.RegistryID)
		}
		if err := s.updateEntity(ctx, sess, r, it); err != nil {
			return err
		}
		version := "latest"
		if it.Version != nil && *it.Version != "" {
			version = *it.Version
		}
		return s.d.Registries.MarkItemApplied(ctx, sess, it.ID, version, s.d.Now())
	})
}

// UpdateAllSpecs is update_all_specs: every item of the registry with an
// update, each on its own; a failure is logged and counted.
func (s *Service) UpdateAllSpecs(ctx context.Context, ws scope.Workspace, registryID string) (updated, failed int, err error) {
	var all []domain.Item
	if err := s.read(ctx, ws, func(sess db.Session) (err error) {
		all, err = s.d.Registries.AllItems(ctx, sess, registryID)
		return err
	}); err != nil {
		return 0, 0, err
	}
	for _, it := range all {
		if !it.UpdateAvailable {
			continue
		}
		if err := s.UpdateItemSpec(ctx, ws, it.ID); err != nil {
			if ctx.Err() != nil && errors.Is(err, ctx.Err()) {
				return updated, failed, err
			}
			s.d.Log.WarnContext(ctx, "Failed to update "+it.Name, "item_id", it.ID, "error", err)
			failed++
			continue
		}
		updated++
	}
	return updated, failed, nil
}
