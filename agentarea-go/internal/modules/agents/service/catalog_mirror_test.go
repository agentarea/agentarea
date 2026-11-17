package service

import (
	"context"
	"strings"
	"testing"

	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

type mirrorFakeItems struct {
	CatalogItems
	folders int
	tokens  []string
}

func (f *mirrorFakeItems) Folder(_ context.Context, token, _, _ string, _, _ *string) (catalogapi.GitHubFolder, error) {
	f.folders++
	f.tokens = append(f.tokens, token)
	if token != "" {
		return catalogapi.GitHubFolder{Commit: "c1", TreeSHA: "t1", Files: map[string][]byte{"SKILL.md": []byte("---\nname: p\ndescription: d\n---\nprivate")}}, nil
	}
	return catalogapi.GitHubFolder{}, &catalogapi.FolderError{Msg: "GitHub throttled", RateLimited: true}
}

func TestCatalogMirrorStoresPackagesAndStopsOnTheRateLimit(t *testing.T) {
	ctx := context.Background()
	_, _, _, b, k, c := skillSetup(t)
	items := &mirrorFakeItems{}
	k.items = items
	ws := c.Workspace.ID()
	mirror, err := CatalogMirror{K: k}.Open(ctx, "reg", &ws, "")
	if err != nil {
		t.Fatal(err)
	}
	pkg, err := mirror(ctx, map[string]any{"content": "---\nname: m\ndescription: d\n---\nbody", "source_url": "https://x"})
	if err != nil {
		t.Fatal(err)
	}
	s3, _ := pkg["s3_path"].(string)
	if !strings.HasPrefix(s3, "skills/"+ws+"/catalog/") || pkg["source_url"] != "https://x" {
		t.Fatalf("package %v", pkg)
	}
	if _, ok := b.objs[s3+"SKILL.md"]; !ok {
		t.Fatal("package not stored")
	}
	gh := map[string]any{"source": map[string]any{"type": "github", "repo": "o/r", "path": "s"}}
	for range 2 {
		if _, err := mirror(ctx, gh); err == nil {
			t.Fatal("a throttled read stored a package")
		}
	}
	if items.folders != 1 {
		t.Fatalf("GitHub asked %d times after its rate limit", items.folders)
	}
	private, err := CatalogMirror{K: k}.Open(ctx, "reg", &ws, "token")
	if err != nil {
		t.Fatal(err)
	}
	pkg, err = private(ctx, gh)
	if err != nil {
		t.Fatalf("private mirror: %v", err)
	}
	s3, _ = pkg["s3_path"].(string)
	if items.tokens[len(items.tokens)-1] != "token" || pkg["tree_sha"] != "t1" || pkg["source_url"] != "https://github.com/o/r/tree/c1/s" ||
		string(b.objs[s3+"SKILL.md"]) != "---\nname: p\ndescription: d\n---\nprivate" {
		t.Fatalf("private package %v (tokens %v)", pkg, items.tokens)
	}
}
