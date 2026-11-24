package operator

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func write(t *testing.T, path, text string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestAManifestDirectoryIsReadInNameOrderWithEveryDocument(t *testing.T) {
	dir := t.TempDir()
	write(t, filepath.Join(dir, "b.yaml"), `apiVersion: agentarea.io/v1alpha1
kind: PlatformEgressExit
metadata: {name: eu}
spec: {name: eu, via: proxy-eu}
`)
	write(t, filepath.Join(dir, "a.yml"), `# comment
---
apiVersion: agentarea.io/v1alpha1
kind: PlatformConnection
metadata: {name: search, namespace: agentarea}
spec: {name: Search, transport: openapi}
---
apiVersion: agentarea.io/v1alpha1
kind: LLMProviderConfig
metadata: {name: or}
`)
	write(t, filepath.Join(dir, "notes.txt"), "not a manifest")
	got, err := ReadManifests([]string{dir}, "default")
	if err != nil {
		t.Fatal(err)
	}
	var seen []string
	for _, d := range got {
		seen = append(seen, d.Kind+" "+d.Namespace+"/"+d.Name)
	}
	want := "platformconnections agentarea/search,llmproviderconfigs default/or,platformegressexits default/eu"
	if strings.Join(seen, ",") != want {
		t.Fatalf("got %v", seen)
	}
	if got[1].Spec == nil || got[0].Spec["transport"] != "openapi" {
		t.Fatalf("specs %v %v", got[0].Spec, got[1].Spec)
	}
}

func TestAManifestOfAnotherKindIsRefused(t *testing.T) {
	path := filepath.Join(t.TempDir(), "m.yaml")
	write(t, path, "apiVersion: v1\nkind: Secret\nmetadata: {name: s}\n")
	if _, err := ReadManifests([]string{path}, "default"); err == nil || !strings.Contains(err.Error(), "not a declared resource") {
		t.Fatalf("err %v", err)
	}
	write(t, path, "apiVersion: agentarea.io/v1alpha1\nkind: PlatformEgressExit\nspec: {}\n")
	if _, err := ReadManifests([]string{path}, "default"); err == nil || !strings.Contains(err.Error(), "metadata.name") {
		t.Fatalf("err %v", err)
	}
}

func TestDirSecretsReadAMountedSecretAndNothingOutsideIt(t *testing.T) {
	dir := t.TempDir()
	write(t, filepath.Join(dir, "tokens", "search"), "tok\n")
	write(t, filepath.Join(dir, "outside"), "x")
	s := DirSecrets{Dir: dir}
	if v, err := s.Read(context.Background(), "agentarea", "tokens", "search"); err != nil || v != "tok" {
		t.Fatalf("%q %v", v, err)
	}
	if _, err := s.Read(context.Background(), "agentarea", "tokens", "missing"); err == nil || !strings.Contains(err.Error(), "not found in Secret 'tokens'") {
		t.Fatalf("err %v", err)
	}
	for _, ref := range [][2]string{{"..", "outside"}, {"tokens", "../../outside"}, {"", "search"}} {
		if _, err := s.Read(context.Background(), "agentarea", ref[0], ref[1]); err == nil {
			t.Fatalf("%v read", ref)
		}
	}
	if _, err := (DirSecrets{}).Read(context.Background(), "agentarea", "tokens", "search"); err == nil {
		t.Fatal("read without a directory")
	}
}

func TestApplyReconcilesADeclaredResourceAsTheControllerDoes(t *testing.T) {
	f := &fakePlatform{}
	out := rig(f).Apply(context.Background(), Declared{Kind: KindEgressExit, Namespace: "agentarea", Name: "e",
		Spec: map[string]any{"name": "eu", "via": "proxy-eu"}})
	if out.Status["phase"] != "Synced" || len(f.exits) != 1 || f.exits[0].Name != "eu" {
		t.Fatalf("%v %v", out.Status, f.exits)
	}
}
