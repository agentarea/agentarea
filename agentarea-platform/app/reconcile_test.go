package app

import (
	"bytes"
	"context"
	"errors"
	"os"
	"strings"
	"testing"

	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

func TestReconcileManifestJoinsItsSources(t *testing.T) {
	read := func(string) ([]byte, error) {
		return []byte("- name: from-file\n  source_url: https://example.com/f.json\n  recommendation_priority: 5\n"), nil
	}
	got, err := reconcileManifest(`[{"name":"from-env","source_url":"https://example.com/e.json"}]`, "m.yaml",
		[]string{"https://example.com/registry/skills.json", "./local/models.yaml"}, read)
	if err != nil {
		t.Fatal(err)
	}
	names := []string{}
	for _, e := range got {
		names = append(names, e["name"].(string))
	}
	if strings.Join(names, ",") != "from-env,from-file,skills.json,models" {
		t.Fatalf("names %v", names)
	}
	if got[1]["recommendation_priority"] != float64(5) {
		t.Fatalf("priority %#v", got[1]["recommendation_priority"])
	}
	if got[3]["source_url"] != "./local/models.yaml" {
		t.Fatalf("local source %v", got[3])
	}
}

func TestReconcileManifestRefusesMalformedInput(t *testing.T) {
	if _, err := reconcileManifest(`{"name":"x"}`, "", nil, os.ReadFile); err == nil {
		t.Fatal("an object accepted as the JSON config")
	}
	notList := func(string) ([]byte, error) { return []byte("name: x\n"), nil }
	if _, err := reconcileManifest("", "m.yaml", nil, notList); err == nil {
		t.Fatal("a mapping accepted as the manifest file")
	}
	missing := func(string) ([]byte, error) { return nil, os.ErrNotExist }
	if _, err := reconcileManifest("", "m.yaml", nil, missing); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing file: %v", err)
	}
}

func TestReportReconcileFailsOnAFailedRegistry(t *testing.T) {
	var out bytes.Buffer
	ok := catalogapi.ReconcileResult{Succeeded: []string{"a"}, Skipped: []string{"b"}}
	if err := reportReconcile(&out, 2, ok, false); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "1 succeeded, 0 failed, 1 skipped (out of 2)") || !strings.Contains(out.String(), "another reconcile was syncing: b") {
		t.Fatalf("report %q", out.String())
	}
	out.Reset()
	failed := catalogapi.ReconcileResult{Failed: map[string]string{"c": "unreachable"}, WorkspaceFailed: map[string]string{"w": "broken"}}
	if err := reportReconcile(&out, 1, failed, true); !errors.Is(err, ErrReconcileFailed) {
		t.Fatalf("failed run: %v", err)
	}
	if !strings.Contains(out.String(), "  - c: unreachable") || !strings.Contains(out.String(), "0 synced, 1 failed") {
		t.Fatalf("report %q", out.String())
	}
}

func TestReconcileWithoutManifestDoesNothing(t *testing.T) {
	var out bytes.Buffer
	b := &Build{lookup: func(string) (string, bool) { return "", false }, stdout: &out}
	if err := b.runReconcile(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "No registry config provided") {
		t.Fatalf("output %q", out.String())
	}
	if err := b.runReconcile(context.Background(), []string{"extra"}); !errors.Is(err, ErrUsage) {
		t.Fatalf("positional: %v", err)
	}
}
