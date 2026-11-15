package service

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
)

type testNet struct{ rt http.RoundTripper }

func (n testNet) Transport(netguard.Destination) http.RoundTripper { return n.rt }
func (testNet) Dialer() netguard.Dialer                            { return nil }

func fetcherFor(ts *httptest.Server) Fetcher {
	ep := GitHubEndpoints{API: ts.URL, Raw: ts.URL, Git: ts.URL, Codeload: ts.URL}
	return Fetcher{Net: testNet{rt: ts.Client().Transport}, GitHub: ep}
}

func TestParseUntrustedRefusesYAMLAliasesAndOversizedYAML(t *testing.T) {
	if _, err := ParseUntrusted([]byte("a: &x [1]\nb: *x\n")); err == nil {
		t.Fatal("alias accepted")
	}
	big := []byte("a: " + strings.Repeat("x", MaxYAMLSourceBytes) + "\n")
	var se *SourceError
	if _, err := ParseUntrusted(big); !errors.As(err, &se) || !strings.Contains(se.Msg, "publish it as JSON") {
		t.Fatalf("oversized YAML: %v", err)
	}
	v, err := ParseUntrusted([]byte("skills:\n  - name: s\n    recommendation_rank: 3\n"))
	if err != nil {
		t.Fatal(err)
	}
	items, err := ParseSource(domain.TypeSkills, v)
	if err != nil || len(items) != 1 || *items[0].Rank != 3 {
		t.Fatalf("items %+v, %v", items, err)
	}
}

func TestDetectType(t *testing.T) {
	v, _ := DecodeJSON([]byte(`{"providers": []}`))
	if typ, err := DetectType(v); err != nil || typ != domain.TypeLLMProviders {
		t.Fatalf("%s %v", typ, err)
	}
	v, _ = DecodeJSON([]byte(`{"providers": [], "models": []}`))
	if _, err := DetectType(v); err == nil || !strings.Contains(err.Error(), "ambiguous") {
		t.Fatalf("ambiguous: %v", err)
	}
	if _, err := DetectType([]any{}); err == nil {
		t.Fatal("list root detected")
	}
}

func TestParseRanksDedupesAndRefusesBoolRank(t *testing.T) {
	v, _ := DecodeJSON([]byte(`{"agents": [
		{"name": "a", "recommendation_rank": true},
		{"name": "b", "agentarea:recommendation_rank": 7},
		{"name": "a", "description": "second"}]}`))
	items, err := ParseSource(domain.TypeAgents, v)
	if err != nil {
		t.Fatal(err)
	}
	items = Dedupe(items)
	if len(items) != 2 || items[0].ExternalID != "a" || *items[0].Description != "second" || *items[0].Rank != 2 || *items[1].Rank != 7 {
		t.Fatalf("%+v", items)
	}
}

func TestMCPFormatsAndCommandPinning(t *testing.T) {
	v, _ := DecodeJSON([]byte(`{"servers": [{"server": {"name": "io.x/weather-api", "version": "1.2.0",
		"remotes": [{"type": "sse", "url": "https://w.example", "headers": [{"name": "Authorization"}]}],
		"packages": [{"registryType": "npm", "name": "@x/w"}, {"registryType": "pypi", "name": "w", "version": "latest"}]}}]}`))
	items, err := ParseSource(domain.TypeMCPServers, v)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 2 {
		t.Fatalf("want the remote and the npm command, got %d", len(items))
	}
	if items[0].Name != "Weather API" || fmt.Sprint(items[0].Tags) != "[sse requires-auth]" {
		t.Fatalf("remote %+v", items[0])
	}
	if items[1].ExternalID != "io.x/weather-api/command" || fmt.Sprint(items[1].Spec["args"]) != "[-y @x/w@1.2.0]" {
		t.Fatalf("command %+v", items[1].Spec)
	}
	mixed, _ := DecodeJSON([]byte(`{"servers": [{"server": {"name": "a"}},
		{"registry_id": "b", "connection_type": "url", "json_spec": {}}]}`))
	if _, err := ParseSource(domain.TypeMCPServers, mixed); err == nil || !strings.Contains(err.Error(), "cannot be mixed") {
		t.Fatalf("mixed: %v", err)
	}
}

func TestProviderAndModelChecks(t *testing.T) {
	v, _ := DecodeJSON([]byte(`{"providers": [{"provider_key": "p", "first_party": "yes"}]}`))
	if _, err := ParseSource(domain.TypeLLMProviders, v); err == nil {
		t.Fatal("non-bool first_party accepted")
	}
	if _, err := providerRow(domain.Item{Name: "P"}, map[string]any{"provider_key": "p", "transport": "grpc"}); err == nil {
		t.Fatal("unknown transport accepted")
	}
	p, err := providerRow(domain.Item{Name: "P"}, map[string]any{"provider_key": "p", "auth": nil, "cache_breakpoints": true})
	if err != nil || p.Contract.Auth.Value != "bearer" || !p.Contract.CacheBreakpoints.Value || p.Contract.Transport != nil {
		t.Fatalf("%+v %v", p.Contract, err)
	}
	spec := map[string]any{"model_name": "m", "kind": "chat"}
	if _, err := modelRow(domain.Item{}, spec, [16]byte{}); err == nil || !strings.Contains(err.Error(), "context_window") {
		t.Fatalf("chat model without context window: %v", err)
	}
	if _, err := modelRow(domain.Item{}, map[string]any{"model_name": "i", "kind": "image"}, [16]byte{}); err != nil {
		t.Fatalf("image model: %v", err)
	}
}

func TestSyncErrorMessageNeverEchoesTheSource(t *testing.T) {
	cases := map[error]string{
		&GitHubError{Msg: "secret detail", Status: 404}:                 "GitHub answered 404",
		&httpStatus{code: 500}:                                          "the source answered HTTP 500",
		&unreachable{err: errors.New("dial tcp 10.0.0.1")}:              "the source could not be reached",
		valueErr("Model 'p/m' has no explicit positive context_window"): "Model 'p/m' has no explicit positive context_window",
		errors.New("pq: relation x"):                                    "the sync failed; the server log has the cause",
	}
	for err, want := range cases {
		if got := SyncErrorMessage(err); got != want {
			t.Errorf("%v: %q, want %q", err, got, want)
		}
	}
}

func TestWorkspaceSourceCapsAndHTTPS(t *testing.T) {
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/big":
			_, _ = w.Write(bytes.Repeat([]byte(" "), MaxSourceBytes+1))
		case "/gone":
			http.Error(w, "private detail", http.StatusNotFound)
		default:
			w.Header().Set("ETag", `"e1"`)
			_, _ = w.Write([]byte(`{"skills": []}`))
		}
	}))
	defer ts.Close()
	f := fetcherFor(ts)
	ctx := context.Background()
	if _, err := f.WorkspaceSource(ctx, "http://example.com/x"); err == nil {
		t.Fatal("http accepted")
	}
	var se *SourceError
	if _, err := f.WorkspaceSource(ctx, ts.URL+"/big"); !errors.As(err, &se) || !strings.Contains(se.Msg, "larger than 5 MB") {
		t.Fatalf("big: %v", err)
	}
	if _, err := f.WorkspaceSource(ctx, ts.URL+"/gone"); !errors.As(err, &se) || se.Msg != "the source answered HTTP 404" {
		t.Fatalf("gone: %v", err)
	}
	if e, err := f.WorkspaceEtag(ctx, ts.URL+"/i"); err != nil || e == nil || *e != `"e1"` {
		t.Fatalf("etag %v %v", e, err)
	}
}

func tarball(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	tw := tar.NewWriter(zw)
	for name, body := range files {
		if err := tw.WriteHeader(&tar.Header{Name: "repo-abc/" + name, Mode: 0o644, Size: int64(len(body)), Typeflag: tar.TypeReg}); err != nil {
			t.Fatal(err)
		}
		_, _ = tw.Write([]byte(body))
	}
	_ = tw.Close()
	_ = zw.Close()
	return buf.Bytes()
}

func TestTokenFreeGitHubIndexHashesTreesAsGit(t *testing.T) {
	commit := strings.Repeat("a", 40)
	archive := tarball(t, map[string]string{
		"skills/pdf/SKILL.md": "---\nname: pdf\ndescription: Read PDFs\n---\nbody\n",
		"skills/pdf/run.sh":   "echo\n",
		"README.md":           "hi\n",
	})
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/git-upload-pack"):
			line := commit + " HEAD\n"
			_, _ = fmt.Fprintf(w, "%04x%s0000", len(line)+4, line)
		case strings.Contains(r.URL.Path, "/tar.gz/"):
			_, _ = w.Write(archive)
		default:
			http.NotFound(w, r)
		}
	}))
	defer ts.Close()
	gh := fetcherFor(ts).Repo("")
	ctx := context.Background()
	head, err := gh.Head(ctx, "o/r", nil)
	if err != nil || head != commit {
		t.Fatalf("head %s %v", head, err)
	}
	items, err := BuildGitHubSkillIndex(ctx, gh, "o/r", head, nil, 0)
	if err != nil || len(items) != 1 {
		t.Fatalf("%+v %v", items, err)
	}
	if *items[0].Version != "32221f493ec3b37ba2d48ab2d739dfd821c5cddb" || items[0].Name != "pdf" || items[0].ExternalID != "skills/pdf" {
		t.Fatalf("item %+v", items[0])
	}
	sorted := gitTreeSHAs(map[string]gitFile{"a-b": {mode: "100644", sha: blobSHA(nil)}, "a/x": {mode: "100644", sha: blobSHA(nil)}})
	if sorted[""] != "e3fb51926fb44348f67a7719bccacdf39d28ea93" {
		t.Fatalf("a folder sorts as name/: %s", sorted[""])
	}
	if blobSHA([]byte("hi\n")) != "45b983be36b73c0788dc9cbcb76cbb80fc7bb057" {
		t.Fatal("blob sha differs from git's")
	}
	if _, err := BuildGitHubSkillIndex(ctx, gh, "o/r", head, nil, 0); err != nil {
		t.Fatal(err)
	}
	pt := fetcherFor(ts).NewPointerTrees()
	if tree, err := pt.Tree(ctx, map[string]any{"repo": "o/r", "path": "skills/pdf"}); err != nil || tree != *items[0].Version {
		t.Fatalf("pointer tree %s %v", tree, err)
	}
}

func TestReconcilePatchNamesWhatChangedAndRefusesATypeChange(t *testing.T) {
	ref := "main"
	existing := domain.Registry{Name: "r", RegistryType: domain.TypeSkills, SourceType: "url", SourceURL: "https://a",
		Mode: "mirror", Trust: "official", RecommendationPriority: 100, SourceRef: &ref}
	p, changed, err := reconcilePatch(existing, map[string]any{"name": "r", "source_url": "https://b", "trust": "official"}, nil)
	if err != nil || fmt.Sprint(changed) != "[source_url source_ref]" || !p.SourceRef.Set || p.SourceRef.Value != nil {
		t.Fatalf("%v %v", changed, err)
	}
	if _, _, err := reconcilePatch(existing, map[string]any{"name": "r", "source_url": "https://a", "type": "agents"}, nil); err == nil {
		t.Fatal("type change accepted")
	}
	if err := validateManifest([]map[string]any{{"name": "gone", "active": false}, {"name": "x"}}); err == nil ||
		!strings.Contains(err.Error(), "Registry entry 1") {
		t.Fatalf("manifest: %v", err)
	}
}
