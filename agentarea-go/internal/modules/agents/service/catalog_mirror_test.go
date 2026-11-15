package service

import (
	"context"
	"errors"
	"strings"
	"testing"

	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

type mirrorFakeItems struct {
	CatalogItems
	folders int
}

func (f *mirrorFakeItems) Folder(context.Context, string, string, *string, *string) (catalogapi.GitHubFolder, error) {
	f.folders++
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
	private, _ := CatalogMirror{K: k}.Open(ctx, "reg", &ws, "token")
	if _, err := private(ctx, gh); !errors.Is(err, ErrPrivateMirror) {
		t.Fatalf("private mirror: %v", err)
	}
}
