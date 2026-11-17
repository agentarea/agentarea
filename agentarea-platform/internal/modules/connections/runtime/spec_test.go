package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

func build(t *testing.T, d Deps, spec map[string]any) (workload.Spec, error) {
	t.Helper()
	return newRuntime(t, d).buildSpec(context.Background(), &instance{ID: "inst-1", WorkspaceID: "ws-1", Spec: spec})
}

func TestCommandInstanceRunsOnMCPBase(t *testing.T) {
	s, err := build(t, testDeps(&fakeBackend{}, time.Second), map[string]any{"type": "command", "command": "npx", "args": []any{"-y", "@acme/mcp"}})
	if err != nil {
		t.Fatal(err)
	}
	if s.Image != "agentarea/agentarea-mcp-base:test" || s.Port != 8080 || !slices.Equal(s.Command, []string{"npx", "-y", "@acme/mcp"}) {
		t.Fatalf("spec = %+v", s)
	}
	if s.InstanceID != "inst-1" || s.WorkspaceID != "ws-1" || s.Name != "inst-1" {
		t.Fatalf("identity = %+v", s)
	}
}

func TestDockerInstanceRunsItsImage(t *testing.T) {
	s, err := build(t, testDeps(&fakeBackend{}, time.Second), map[string]any{
		"type": "docker", "image": "ghcr.io/acme/mcp:1", "port": json.Number("9000"),
		"cmd": []any{"serve"}, "args": []any{"--transport=stdio", "--http"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if s.Image != "ghcr.io/acme/mcp:1" || s.Port != 9000 || !slices.Equal(s.Command, []string{"serve", "--http"}) {
		t.Fatalf("spec = %+v", s)
	}
}

func TestDockerPortDefaultsAndRefusals(t *testing.T) {
	s, err := build(t, testDeps(&fakeBackend{}, time.Second), map[string]any{"type": "docker", "image": "a/b:1"})
	if err != nil || s.Port != 8000 {
		t.Fatalf("absent port: %d %v", s.Port, err)
	}
	for _, port := range []any{json.Number("80.5"), "8080", json.Number("70000"), float64(1.5)} {
		if _, err := instancePort(map[string]any{"type": "docker", "port": port}); err == nil {
			t.Errorf("port %#v accepted", port)
		}
	}
}

func TestStdioImageIsRefused(t *testing.T) {
	_, err := build(t, testDeps(&fakeBackend{}, time.Second), map[string]any{
		"type": "docker", "image": "ghcr.io/acme/mcp:1",
		"packages": []any{map[string]any{"registryType": "oci", "identifier": "ghcr.io/acme/mcp:2", "transport": map[string]any{"type": "stdio"}}},
	})
	var refused *SpecRefusedError
	if !errors.As(err, &refused) || !strings.Contains(refused.Reason, "stdio") {
		t.Fatalf("err = %v", err)
	}
}

func TestEnvironmentResolvesSecretsLabelsAndKeys(t *testing.T) {
	d := testDeps(&fakeBackend{}, time.Second)
	d.Secrets = fakeSecrets{values: map[string]string{"github_token": "ghp_x", InstanceSecretName("inst-1", "API_KEY"): "k1"}}
	d.Storage = fakeStorage{env: map[string]string{"MCP_STORAGE_TOKEN": "tok"}}
	var hooked string
	d.SpecHook = func(_ context.Context, id, ws string, s *workload.Spec) error {
		hooked = id + "/" + ws
		s.Environment["HTTPS_PROXY"] = "http://egress"
		return nil
	}
	s, err := build(t, d, map[string]any{
		"type": "command", "command": "uvx",
		"environment": map[string]any{"PLAIN": "v", "TOKEN": map[string]any{"secret_name": "github_token"}},
		"env_vars":    []any{"API_KEY"},
		"labels":      map[string]any{"team": "a", egressLabel: "open", "agentarea.io/dataplane-id": "dp-other", "agentarea.io/instance-id": "x"},
		"context":     map[string]any{"enabled": true},
	})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]string{
		"PLAIN": "v", "TOKEN": "ghp_x", "API_KEY": "k1", "MCP_STORAGE_TOKEN": "tok",
		contextKeyEnv: ContextKey([]byte(testSecret), "inst-1"), "HTTPS_PROXY": "http://egress",
	}
	for k, v := range want {
		if s.Environment[k] != v {
			t.Errorf("env %s = %q, want %q", k, s.Environment[k], v)
		}
	}
	// Python dropped only the egress label: a json_spec could stamp the
	// data-plane owner label and pass as another data plane's workload.
	if len(s.Labels) != 1 || s.Labels["team"] != "a" {
		t.Errorf("labels = %v, want every agentarea.io/ label dropped", s.Labels)
	}
	if hooked != "inst-1/ws-1" {
		t.Errorf("hook saw %q", hooked)
	}
}

func TestMissingInstanceSecretRefusesTheSpec(t *testing.T) {
	if _, err := build(t, testDeps(&fakeBackend{}, time.Second), map[string]any{"type": "command", "command": "x", "env_vars": []any{"NOPE"}}); err == nil {
		t.Fatal("a missing secret started")
	}
}

func TestSpecHookRefusal(t *testing.T) {
	d := testDeps(&fakeBackend{}, time.Second)
	d.SpecHook = func(context.Context, string, string, *workload.Spec) error { return errors.New("no egress exit") }
	if _, err := build(t, d, map[string]any{"type": "command", "command": "x"}); err == nil || !strings.Contains(err.Error(), "no egress exit") {
		t.Fatalf("err = %v", err)
	}
}

func TestSpecHookSeesTheEgressExitTheSpecNames(t *testing.T) {
	d := testDeps(&fakeBackend{}, time.Second)
	var seen []string
	d.SpecHook = func(_ context.Context, _, _ string, s *workload.Spec) error {
		seen = append(seen, s.EgressExit)
		return nil
	}
	for _, exit := range []any{"client-x", nil} {
		if _, err := build(t, d, map[string]any{"type": "command", "command": "x", "egress_exit": exit}); err != nil {
			t.Fatal(err)
		}
	}
	if !slices.Equal(seen, []string{"client-x", ""}) {
		t.Fatalf("hook saw %q", seen)
	}
	for _, bad := range []any{42, []any{"client-x"}} {
		if _, err := build(t, d, map[string]any{"type": "command", "command": "x", "egress_exit": bad}); err == nil || !strings.Contains(err.Error(), "json_spec.egress_exit must be an egress exit id") {
			t.Fatalf("egress_exit %#v: %v", bad, err)
		}
	}
	if raw, _ := json.Marshal(workload.Spec{EgressExit: "client-x"}); strings.Contains(string(raw), "client-x") {
		t.Fatal("the exit reached the wire spec")
	}
}

// The egress hook leaves through the default exit when the merged spec
// requires one; a malformed requirement stops the start before the hook, as
// the mcp-manager overlay refused it (go/internal/egress egressRequired).
func TestSpecHookSeesWhetherTheSpecRequiresAnExit(t *testing.T) {
	d := testDeps(&fakeBackend{}, time.Second)
	var seen []bool
	d.SpecHook = func(_ context.Context, _, _ string, s *workload.Spec) error {
		seen = append(seen, s.EgressRequired)
		return nil
	}
	for _, egress := range []any{map[string]any{"required": true}, map[string]any{"required": false}, nil} {
		if _, err := build(t, d, map[string]any{"type": "command", "command": "x", "egress": egress}); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := build(t, d, map[string]any{"type": "command", "command": "x"}); err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(seen, []bool{true, false, false, false}) {
		t.Fatalf("hook saw %v", seen)
	}
	for name, bad := range map[string]any{
		"a string": "yes", "a bool": true, "a list": []any{true},
		"required not a bool": map[string]any{"required": "true"}, "required missing": map[string]any{},
		"unknown key": map[string]any{"required": true, "region": "se"},
	} {
		_, err := build(t, d, map[string]any{"type": "command", "command": "x", "egress": bad})
		if err == nil || !strings.Contains(err.Error(), "json_spec.egress") {
			t.Fatalf("%s: %v", name, err)
		}
	}
	if len(seen) != 4 {
		t.Fatal("the hook ran for a malformed requirement")
	}
	if raw, _ := json.Marshal(workload.Spec{EgressRequired: true}); strings.Contains(string(raw), "egress") {
		t.Fatal("the requirement reached the wire spec")
	}
}

func TestContextMustBeExactlyEnabled(t *testing.T) {
	for _, bad := range []any{true, map[string]any{"enabled": false}, map[string]any{"enabled": true, "x": 1}} {
		if _, err := contextEnabled(map[string]any{"context": bad}); err == nil {
			t.Errorf("context %#v accepted", bad)
		}
	}
}

func TestMergeContainerSpec(t *testing.T) {
	server := map[string]any{"args": []any{"a"}, "cmd": []any{"x"}, "environment": map[string]any{"A": "1"}}
	spec, err := mergeContainerSpec(server, map[string]any{"image": "own/image:1"}, "docker", nil, "")
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := spec["args"]; ok || spec["image"] != "own/image:1" || spec["type"] != "docker" {
		t.Fatalf("an instance image keeps the server invocation: %v", spec)
	}
	spec, err = mergeContainerSpec(map[string]any{}, map[string]any{}, "command", []any{"npx", "-y", "pkg"}, "")
	if err != nil || spec["command"] != "npx" || len(spec["args"].([]any)) != 2 {
		t.Fatalf("command spec = %v %v", spec, err)
	}
	spec, _ = mergeContainerSpec(map[string]any{}, map[string]any{}, "docker", nil, "catalog/image:2")
	if spec["image"] != "catalog/image:2" {
		t.Fatalf("server image not used: %v", spec)
	}
	if _, err := mergeContainerSpec(map[string]any{}, map[string]any{}, "command", []any{}, ""); err == nil {
		t.Fatal("an empty command accepted")
	}
}

func TestServerSpecMayNotReferenceSecrets(t *testing.T) {
	if err := refuseReferences("server spec", map[string]any{"headers": map[string]any{"X": map[string]any{"secret_name": "s"}}}); err == nil {
		t.Fatal("a server-level reference was accepted")
	}
}

func TestURLServerMergesLegacyKeys(t *testing.T) {
	u, err := urlServer(map[string]any{"type": "url", "url": "https://legacy"}, map[string]any{
		"headers": map[string]any{"A": "b"}, "env_vars": []any{"TOKEN"},
	}, "")
	if err != nil || u.EndpointURL != "https://legacy" || u.Headers["A"] != "b" || !slices.Equal(u.EnvVars, []string{"TOKEN"}) {
		t.Fatalf("u=%+v err=%v", u, err)
	}
	u, _ = urlServer(map[string]any{}, map[string]any{}, "https://remote")
	if u.EndpointURL != "https://remote" {
		t.Fatalf("remote url not used: %+v", u)
	}
	if _, err := urlServer(map[string]any{}, map[string]any{"headers": map[string]any{"A": 1}}, ""); err == nil {
		t.Fatal("a numeric header accepted")
	}
}

func lookup(vars map[string]string) config.Lookup {
	return func(name string) (string, bool) {
		v, ok := vars[name]
		return v, ok
	}
}

func runtimeVars() map[string]string {
	return map[string]string{
		"AGENTAREA_MCP_BACKEND": "docker", "AGENTAREA_MCP_GATEWAY_SECRET": testSecret,
		"AGENTAREA_MCP_LEASE_TTL": "30s", "AGENTAREA_MCP_STARTUP_TIMEOUT": "2m",
		"AGENTAREA_MCP_IDLE_TIMEOUT": "0", "AGENTAREA_MCP_SWEEP_INTERVAL": "1m",
	}
}

func TestLoadConfig(t *testing.T) {
	l := config.New(lookup(runtimeVars()))
	c := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if c.Backend != BackendDocker || c.IdleTimeout != 0 || c.StartupTimeout != 2*time.Minute || c.BaseImage != defaultBaseImage {
		t.Fatalf("config = %+v", c)
	}
}

func TestLoadConfigRefusals(t *testing.T) {
	for name, tc := range map[string]struct {
		set, unset string
		value      string
	}{
		"missing lease":       {unset: "AGENTAREA_MCP_LEASE_TTL"},
		"missing secret":      {unset: "AGENTAREA_MCP_GATEWAY_SECRET"},
		"short secret":        {set: "AGENTAREA_MCP_GATEWAY_SECRET", value: "short"},
		"zero startup":        {set: "AGENTAREA_MCP_STARTUP_TIMEOUT", value: "0"},
		"bare number":         {set: "AGENTAREA_MCP_SWEEP_INTERVAL", value: "60"},
		"unknown backend":     {set: "AGENTAREA_MCP_BACKEND", value: "nomad"},
		"missing idle":        {unset: "AGENTAREA_MCP_IDLE_TIMEOUT"},
		"negative idle":       {set: "AGENTAREA_MCP_IDLE_TIMEOUT", value: "-1s"},
		"missing startup":     {unset: "AGENTAREA_MCP_STARTUP_TIMEOUT"},
		"missing sweep":       {unset: "AGENTAREA_MCP_SWEEP_INTERVAL"},
		"zero lease rejected": {set: "AGENTAREA_MCP_LEASE_TTL", value: "0"},
	} {
		t.Run(name, func(t *testing.T) {
			vars := runtimeVars()
			if tc.unset != "" {
				delete(vars, tc.unset)
			}
			name := tc.unset
			if tc.set != "" {
				vars[tc.set], name = tc.value, tc.set
			}
			l := config.New(lookup(vars))
			LoadConfig(l)
			if err := l.Err(); err == nil || !strings.Contains(err.Error(), name) {
				t.Fatalf("err = %v, want %s named", err, name)
			}
		})
	}
}

func TestBackendDetection(t *testing.T) {
	if b := LoadBackend(config.New(lookup(map[string]string{"KUBERNETES_SERVICE_HOST": "10.0.0.1"}))); b != BackendKubernetes {
		t.Fatalf("in cluster: %s", b)
	}
	if b := LoadBackend(config.New(lookup(map[string]string{"AGENTAREA_MCP_BACKEND": "dataplane", "KUBERNETES_SERVICE_HOST": "x"}))); b != BackendDataplane {
		t.Fatalf("explicit: %s", b)
	}
}
