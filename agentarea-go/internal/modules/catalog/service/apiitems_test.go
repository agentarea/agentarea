package service

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
)

func TestAPIItemIsAnOpenAPIItemOfAnActiveMCPRegistry(t *testing.T) {
	st := &fakeRegistries{
		registries: map[string]domain.Registry{
			"r1": {ID: "r1", RegistryType: "mcp_servers", IsActive: true},
			"r2": {ID: "r2", RegistryType: "mcp_servers"},
			"r3": {ID: "r3", RegistryType: "skills", IsActive: true},
		},
		items: map[string]domain.Item{
			"ok":       {ID: "ok", RegistryID: "r1", Name: "Stripe", Spec: json.RawMessage(`{"connection_type":"openapi","n":1.50}`)},
			"mcp":      {ID: "mcp", RegistryID: "r1", Name: "M", Spec: json.RawMessage(`{"connection_type":"mcp"}`)},
			"inactive": {ID: "inactive", RegistryID: "r2", Spec: json.RawMessage(`{"connection_type":"openapi"}`)},
			"skill":    {ID: "skill", RegistryID: "r3", Spec: json.RawMessage(`{"connection_type":"openapi"}`)},
			"nospec":   {ID: "nospec", RegistryID: "r1"},
		},
	}
	s := newService(st, false)
	ctx := context.Background()
	it, err := s.APIItem(ctx, ws(t), "ok")
	if err != nil || it.Name != "Stripe" || it.Spec["n"] != json.Number("1.50") {
		t.Fatalf("%+v %v", it, err)
	}
	for _, id := range []string{"mcp", "inactive", "skill", "nospec"} {
		if _, err := s.APIItem(ctx, ws(t), id); !errors.Is(err, api.ErrNotAPIItem) {
			t.Errorf("%s: %v", id, err)
		}
	}
	if _, err := s.APIItem(ctx, ws(t), "gone"); !errors.Is(err, api.ErrAPIItemNotFound) {
		t.Fatalf("missing: %v", err)
	}
}
