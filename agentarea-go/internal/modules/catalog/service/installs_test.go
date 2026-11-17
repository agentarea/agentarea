package service

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

func TestFolderWithATokenReadsAPrivateRepositoryOverTheAPI(t *testing.T) {
	const commit = "0123456789abcdef0123456789abcdef01234567"
	body := []byte("---\nname: s\ndescription: d\n---\nbody")
	ref := []byte("ref")
	var unauthorized []string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" {
			unauthorized = append(unauthorized, r.URL.Path)
			http.NotFound(w, r)
			return
		}
		switch r.URL.Path {
		case "/repos/o/r/commits/HEAD":
			_ = json.NewEncoder(w).Encode(map[string]any{"sha": commit})
		case "/repos/o/r/git/trees/" + commit:
			_ = json.NewEncoder(w).Encode(map[string]any{"sha": "root", "truncated": false, "tree": []map[string]any{
				{"path": "skills", "type": "tree", "sha": "t-skills"},
				{"path": "skills/s", "type": "tree", "sha": "t-s"},
				{"path": "skills/s/SKILL.md", "type": "blob", "mode": "100644", "sha": blobSHA(body), "size": len(body)},
				{"path": "skills/s/refs/a.md", "type": "blob", "mode": "100644", "sha": blobSHA(ref), "size": len(ref)},
				{"path": "skills/s/.env", "type": "blob", "mode": "100644", "sha": "x", "size": 1},
				{"path": "skills/s/link", "type": "blob", "mode": "120000", "sha": "y", "size": 1},
				{"path": "skills/s/sub", "type": "commit", "sha": "z"},
				{"path": "skills/other/SKILL.md", "type": "blob", "mode": "100644", "sha": "w", "size": 1},
			}})
		case "/o/r/" + commit + "/skills/s/SKILL.md":
			_, _ = w.Write(body)
		case "/o/r/" + commit + "/skills/s/refs/a.md":
			_, _ = w.Write(ref)
		default:
			http.NotFound(w, r)
		}
	}))
	defer ts.Close()
	x := Installs{Fetch: fetcherFor(ts)}
	ctx := context.Background()

	f, err := x.Folder(ctx, "tok", "o/r", "/skills/s/", nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if f.Commit != commit || f.TreeSHA != "t-s" || len(f.Files) != 2 || string(f.Files["SKILL.md"]) != string(body) || string(f.Files["refs/a.md"]) != "ref" {
		t.Fatalf("folder %+v", f)
	}
	if len(unauthorized) > 0 {
		t.Fatalf("read without the token: %v", unauthorized)
	}

	pinned := "t-other"
	if _, err := x.Folder(ctx, "tok", "o/r", "skills/s", nil, &pinned); err == nil || !strings.Contains(err.Error(), "not t-other as the catalog pins it") {
		t.Fatalf("tree mismatch: %v", err)
	}
	var fe *api.FolderError
	if _, err := x.Folder(ctx, "tok", "o/r", "skills/gone", nil, nil); !errors.As(err, &fe) || !fe.NotFound {
		t.Fatalf("missing folder: %v", err)
	}
	if _, err := x.Folder(ctx, "tok", "o/missing", "s", nil, nil); !errors.As(err, &fe) || !fe.NotFound {
		t.Fatalf("missing repository: %v", err)
	}
}

func TestFolderWithATokenRefusesABlobThatDoesNotMatchItsSHA(t *testing.T) {
	const commit = "0123456789abcdef0123456789abcdef01234567"
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/repos/o/r/git/trees/" + commit:
			_ = json.NewEncoder(w).Encode(map[string]any{"sha": "root", "tree": []map[string]any{
				{"path": "SKILL.md", "type": "blob", "mode": "100644", "sha": blobSHA([]byte("expected")), "size": 8},
			}})
		case "/o/r/" + commit + "/SKILL.md":
			_, _ = w.Write([]byte("tampered"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer ts.Close()
	c := commit
	_, err := Installs{Fetch: fetcherFor(ts)}.Folder(context.Background(), "tok", "o/r", "", &c, nil)
	if err == nil || !strings.Contains(err.Error(), "does not match its blob SHA") {
		t.Fatalf("tampered blob: %v", err)
	}
}
