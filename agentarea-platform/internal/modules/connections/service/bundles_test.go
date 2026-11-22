package service

import (
	"context"
	"errors"
	"net/http"
	"reflect"
	"testing"

	"github.com/google/uuid"

	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

func TestBundleUpdateMCPReplacesSpecAndInstanceKeepingTheSecret(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	b := BundleMCPs{S: func() *Service { return f.svc }}
	schema := []any{map[string]any{"name": "TOKEN", "isSecret": true}, map[string]any{"name": "ROOT", "isSecret": false}}
	made, err := b.CreateWithSpec(ctx, f.c, catalogapi.MCPSpecNew{Name: "fs", Cmd: []any{"npx", "fs"}, EnvSchema: schema,
		JSONSpec: map[string]any{"type": "command", "command": "npx", "args": []any{"fs"}}},
		catalogapi.BundleInstance{Name: "fs", JSONSpec: map[string]any{"environment": map[string]any{"TOKEN": "t0k", "ROOT": "/a"}}})
	if err != nil {
		t.Fatal(err)
	}
	retiredAtCreate := len(f.runtime.retired)
	err = b.UpdateMCP(ctx, f.c, made.InstanceID, catalogapi.BundleMCPUpdate{
		Spec: &catalogapi.MCPSpecNew{Name: "fs2", Cmd: []any{"npx", "fs2"}, EnvSchema: schema,
			JSONSpec: map[string]any{"type": "command", "command": "npx", "args": []any{"fs2"}}},
		Instance: catalogapi.BundleInstance{Name: "fs2", JSONSpec: map[string]any{"environment": map[string]any{"TOKEN": b.KeepSecret(), "ROOT": "/b"}}},
	})
	if err != nil {
		t.Fatal(err)
	}
	sp := f.specs.specs[made.SpecID]
	if sp.Name != "fs2" || !reflect.DeepEqual(sp.Cmd, []any{"npx", "fs2"}) {
		t.Fatalf("spec = %+v", sp)
	}
	if len(f.runtime.retired) != retiredAtCreate+1 {
		t.Fatalf("retired %v: a moved command must restart", f.runtime.retired)
	}
	inst, err := f.svc.GetInstance(ctx, f.c, uuid.MustParse(made.InstanceID))
	if err != nil {
		t.Fatal(err)
	}
	env := inst.JSONSpec["environment"].(map[string]any)
	if inst.Name != "fs2" || env["ROOT"] != "/b" || env["TOKEN"] != nil {
		t.Fatalf("instance = %+v", inst)
	}
	if f.secrets.values[domain.InstanceSecretName(made.InstanceID, "TOKEN")] != "t0k" || !reflect.DeepEqual(inst.EnvVars(), []string{"TOKEN"}) {
		t.Fatalf("secret not kept: %v, env_vars %v", f.secrets.values, inst.EnvVars())
	}

	err = b.UpdateMCP(ctx, f.c, made.InstanceID, catalogapi.BundleMCPUpdate{
		Instance: catalogapi.BundleInstance{Name: "fs2", JSONSpec: map[string]any{"environment": map[string]any{"TOKEN": b.KeepSecret(), "ROOT": "/c"}}},
	})
	if err != nil || len(f.runtime.retired) != retiredAtCreate+2 {
		t.Fatalf("instance-only update: %v, retired %v", err, f.runtime.retired)
	}
	err = b.UpdateMCP(ctx, f.c, made.InstanceID, catalogapi.BundleMCPUpdate{
		Spec: &catalogapi.MCPSpecNew{Name: "fs2", Cmd: []any{"npx", "fs3"}, EnvSchema: schema,
			JSONSpec: map[string]any{"type": "command", "command": "npx", "args": []any{"fs3"}}},
		Instance: catalogapi.BundleInstance{Name: "fs2", JSONSpec: map[string]any{"environment": map[string]any{"TOKEN": b.KeepSecret(), "ROOT": "/c"}}},
	})
	if err != nil || len(f.runtime.retired) != retiredAtCreate+3 {
		t.Fatalf("spec-only move: %v, retired %v", err, f.runtime.retired)
	}
	if err := b.UpdateMCP(ctx, f.c, uuid.NewString(), catalogapi.BundleMCPUpdate{}); !errors.Is(err, catalogapi.ErrBundleEntityGone) {
		t.Fatalf("update of a gone instance: %v", err)
	}
}

func TestBundleRediscoverCountsTheToolsServedNow(t *testing.T) {
	f, _ := newVerifyFixture(t, http.DefaultTransport)
	ctx := context.Background()
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"node", "server.js"}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID, JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	f.waitTerminal(t, v.Instance.ID)
	got, err := BundleMCPs{S: func() *Service { return f.svc }}.Rediscover(ctx, f.c, v.Instance.ID)
	if err != nil || got.Status != domain.VerifySucceeded || got.Tools != 1 || got.Error != nil {
		t.Fatalf("rediscover = %+v, %v", got, err)
	}
}
