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

func TestBundleUpdateMCPAndRediscoverNeedEditOnTheInstance(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	b := BundleMCPs{S: func() *Service { return f.svc }}
	made, err := b.CreateWithSpec(ctx, f.c, catalogapi.MCPSpecNew{Name: "fs", Cmd: []any{"npx", "fs"}},
		catalogapi.BundleInstance{Name: "fs", JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	if spec, ok, err := b.InstanceSpecID(ctx, f.c, made.InstanceID); err != nil || !ok || spec != made.SpecID {
		t.Fatalf("spec of the instance = %s %v %v", spec, ok, err)
	}
	f.graph.denied = map[string]bool{made.InstanceID: true}
	err = b.UpdateMCP(ctx, f.c, made.InstanceID, catalogapi.BundleMCPUpdate{Instance: catalogapi.BundleInstance{Name: "x", JSONSpec: map[string]any{}}})
	var refusal *catalogapi.BundleRefusal
	if !errors.As(err, &refusal) || refusal.Msg != "you may not edit MCP instance "+made.InstanceID {
		t.Fatalf("update without edit: %v", err)
	}
	if _, err := b.Rediscover(ctx, f.c, made.InstanceID); !errors.As(err, &refusal) {
		t.Fatalf("rediscover without edit: %v", err)
	}
	f.graph.denied = map[string]bool{made.SpecID: true}
	err = b.UpdateMCP(ctx, f.c, made.InstanceID, catalogapi.BundleMCPUpdate{Spec: &catalogapi.MCPSpecNew{Name: "fs", Cmd: []any{"npx", "fs2"}},
		Instance: catalogapi.BundleInstance{Name: "fs", JSONSpec: map[string]any{}}})
	if !errors.As(err, &refusal) || refusal.Msg != "you may not edit MCP server spec "+made.SpecID {
		t.Fatalf("spec update without edit: %v", err)
	}
}

func TestBundleSecretsMatchComparesWithoutRevealing(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	b := BundleMCPs{S: func() *Service { return f.svc }}
	url := "https://mcp.example.com/mcp"
	made, err := b.CreateWithSpec(ctx, f.c, catalogapi.MCPSpecNew{Name: "remote", RemoteURL: &url,
		EnvSchema: []any{map[string]any{"name": "Authorization", "isSecret": true}}},
		catalogapi.BundleInstance{Name: "remote", JSONSpec: map[string]any{"headers": map[string]any{"Authorization": "Bearer t0k"}}})
	if err != nil {
		t.Fatal(err)
	}
	ctxSecret := "0123456789abcdef-context"
	if err := b.UpdateMCP(ctx, f.c, made.InstanceID, catalogapi.BundleMCPUpdate{SetContextSecret: true,
		Instance: catalogapi.BundleInstance{Name: "remote", JSONSpec: map[string]any{"headers": map[string]any{"Authorization": b.KeepSecret()}},
			ContextSecret: &ctxSecret}}); err != nil {
		t.Fatal(err)
	}
	same, contextSame, err := b.SecretsMatch(ctx, f.c, made.InstanceID,
		map[string]string{"Authorization": "Bearer t0k", "Missing": "x"}, &ctxSecret)
	if err != nil || !same["Authorization"] || same["Missing"] || !contextSame {
		t.Fatalf("same = %v, context %v, %v", same, contextSame, err)
	}
	other := "another-context-secret-value"
	same, contextSame, err = b.SecretsMatch(ctx, f.c, made.InstanceID, map[string]string{"Authorization": "Bearer n3w"}, &other)
	if err != nil || same["Authorization"] || contextSame {
		t.Fatalf("different values matched: %v %v %v", same, contextSame, err)
	}
	f.graph.denied = map[string]bool{made.InstanceID: true}
	var refusal *catalogapi.BundleRefusal
	if _, _, err := b.SecretsMatch(ctx, f.c, made.InstanceID, map[string]string{"Authorization": "x"}, nil); !errors.As(err, &refusal) {
		t.Fatalf("compare without edit: %v", err)
	}
}
