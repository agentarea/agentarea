//go:build suite

// Package sandbox pins /v1/workspaces/{workspace}/files and /sandboxes
// (.omc/research/go-migration/dossiers/sandbox.md, section 2).
package sandbox

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

func digest(data string) string {
	s := sha256.Sum256([]byte(data))
	return hex.EncodeToString(s[:])
}

// upload plans path through c and PUTs data to the presigned URL.
func upload(t *testing.T, w *h.Workspace, c *h.Client, path, data string) {
	t.Helper()
	plan := c.Post(t, w.Path("/files/upload-urls"), map[string]any{
		"files": []any{map[string]any{"path": path, "sha256": digest(data)}},
	}).Expect(http.StatusOK).Object()
	entry := plan["uploads"].([]any)[0].(map[string]any)
	if entry["status"] != "upload" {
		t.Fatalf("plan for %s: %v", path, entry)
	}
	req, err := http.NewRequest(http.MethodPut, entry["upload_url"].(string), bytes.NewReader([]byte(data)))
	if err != nil {
		t.Fatal(err)
	}
	for k, v := range entry["headers"].(map[string]any) {
		req.Header.Set(k, v.(string))
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("PUT %s: %d %s", path, resp.StatusCode, body)
	}
}

func file(path string, size int, contentType string) map[string]any {
	return map[string]any{"path": path, "size": size, "content_type": contentType, "last_modified": h.AnyString}
}

func TestUploadPlanListDownload(t *testing.T) {
	w := h.NewWorkspace(t)
	upload(t, w, w.Owner, "notes/plan.md", "# plan\n")

	sum := digest("# plan\n")
	w.Owner.Post(t, w.Path("/files/upload-urls"), map[string]any{
		"files": []any{
			map[string]any{"path": "notes/plan.md", "sha256": sum},
			map[string]any{"path": "tasks/x.txt", "sha256": sum},
		},
	}).Expect(http.StatusOK).Match(map[string]any{"uploads": []any{
		map[string]any{"path": "notes/plan.md", "status": "unchanged", "upload_url": nil, "method": nil, "headers": nil, "expires_in": nil, "error": nil},
		map[string]any{"path": "tasks/x.txt", "status": "error", "upload_url": nil, "method": nil, "headers": nil, "expires_in": nil,
			"error": "'tasks/x.txt' is a reserved prefix and cannot be written directly"},
	}})

	w.Owner.Get(t, w.Path("/files")).Expect(http.StatusOK).Match(map[string]any{
		"files":       []any{file("notes/plan.md", 7, "text/markdown")},
		"directories": []any{},
		"truncated":   false,
	})

	w.Owner.Get(t, w.Path("/files/notes/plan.md")).Expect(http.StatusOK).Match(map[string]any{
		"url":  h.Current(t).BaseURL + w.Path("/files/download/notes/plan.md"),
		"path": "notes/plan.md",
	})

	resp := w.Owner.Get(t, w.Path("/files/download/notes/plan.md")).Expect(http.StatusOK)
	if string(resp.Body) != "# plan\n" {
		t.Fatalf("body %q", resp.Body)
	}
	if ct := resp.Header.Get("Content-Type"); ct != "text/markdown; charset=utf-8" {
		t.Fatalf("content-type %q", ct)
	}
	if cd := resp.Header.Get("Content-Disposition"); cd != `attachment; filename="plan.md"; filename*=UTF-8''plan.md` {
		t.Fatalf("content-disposition %q", cd)
	}
	if resp.Header.Get("X-Content-Type-Options") != "nosniff" || resp.Header.Get("Content-Length") != "7" {
		t.Fatalf("headers %v", resp.Header)
	}

	w.Owner.Get(t, w.Path("/files/history?path=/notes/plan.md")).Expect(http.StatusOK).Match(map[string]any{
		"path": "notes/plan.md",
		"events": []any{map[string]any{
			"action": "created", "actor_type": "user", "created_by": w.People.Owner.ID,
			"agent_id": nil, "task_id": nil, "created_at": h.AnyString,
		}},
	})
}

func TestArchiveAndRestore(t *testing.T) {
	w := h.NewWorkspace(t)
	upload(t, w, w.Member, "doc.txt", "v1")

	archived := w.Member.Delete(t, w.Path("/files/doc.txt")).Expect(http.StatusOK).Match(map[string]any{
		"path": "doc.txt", "archived_path": h.Pattern(`^\.trash/\d{8}T\d{6}\.\d{6}Z/doc\.txt$`),
	}).Object()["archived_path"].(string)

	w.Member.Get(t, w.Path("/files")).Expect(http.StatusOK).Match(map[string]any{
		"files": []any{}, "directories": []any{}, "truncated": false,
	})
	w.Member.Get(t, w.Path("/files/download/doc.txt")).Expect(http.StatusNotFound).Match(h.Problem(404, "http_error", "File not found"))
	w.Member.Delete(t, w.Path("/files/doc.txt")).Expect(http.StatusNotFound)

	upload(t, w, w.Owner, "doc.txt", "v2")
	w.Owner.Post(t, w.Path("/files/restore/"+archived), nil).Expect(http.StatusOK).Match(map[string]any{
		"path": "doc.txt", "restored_from": archived, "archived_current": h.Pattern(`^\.trash/.+/doc\.txt$`),
	})
	if got := w.Owner.Get(t, w.Path("/files/download/doc.txt")).Expect(http.StatusOK).Body; string(got) != "v1" {
		t.Fatalf("restored %q", got)
	}

	w.Owner.Post(t, w.Path("/files/restore/doc.txt"), nil).Expect(http.StatusBadRequest).Match(h.Problem(400, "http_error", "Not an archived file"))
	w.Owner.Delete(t, w.Path("/files/staging/x")).Expect(http.StatusBadRequest).Match(h.Problem(400, "http_error", "'staging/x' is not a workspace library file"))
	w.Owner.Delete(t, w.Path("/files/apps/x")).Expect(http.StatusForbidden)
}

func TestDirectoriesAndMove(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/files/directories"), map[string]any{"path": "src/"}).Expect(http.StatusCreated).Match(map[string]any{"path": "src/"})
	w.Owner.Post(t, w.Path("/files/directories"), map[string]any{"path": "src"}).Expect(http.StatusConflict).
		Match(h.Problem(409, "http_error", "A folder already exists at this path"))
	upload(t, w, w.Owner, "src/a.txt", "a")

	w.Owner.Post(t, w.Path("/files/move"), map[string]any{"source": "src", "destination": "src/in"}).
		Expect(http.StatusUnprocessableEntity).Match(h.Problem(422, "http_error", "Cannot move a folder into itself"))
	w.Owner.Post(t, w.Path("/files/move"), map[string]any{"source": "src/", "destination": "dst"}).
		Expect(http.StatusOK).Match(map[string]any{"source": "src", "destination": "dst", "moved": 2})
	w.Owner.Get(t, w.Path("/files")).Expect(http.StatusOK).Match(map[string]any{
		"files": []any{file("dst/a.txt", 1, "text/plain")}, "directories": []any{"dst/"}, "truncated": false,
	})
	w.Owner.Post(t, w.Path("/files/move"), map[string]any{"source": "nothing", "destination": "else"}).
		Expect(http.StatusNotFound).Match(h.Problem(404, "http_error", "File not found"))

	event := func(action string) map[string]any {
		return map[string]any{
			"action": action, "actor_type": "user", "created_by": w.People.Owner.ID,
			"agent_id": nil, "task_id": nil, "created_at": h.AnyString,
		}
	}
	w.Owner.Get(t, w.Path("/files/history?path=dst/a.txt")).Expect(http.StatusOK).Match(map[string]any{
		"path": "dst/a.txt", "events": []any{event("moved"), event("created")},
	})
	w.Owner.Get(t, w.Path("/files/history?path=src/a.txt")).Expect(http.StatusOK).Match(map[string]any{
		"path": "src/a.txt", "events": []any{},
	})
}

func TestPresignedAttachment(t *testing.T) {
	w := h.NewWorkspace(t)
	resp := w.Owner.Post(t, w.Path("/files/upload-url"), map[string]any{
		"filename": "in/report.pdf", "content_type": "application/pdf", "sha256": digest("pdf"), "size": 3,
	}).Expect(http.StatusOK).Match(map[string]any{
		"ref": h.Pattern(`^staging/[0-9a-f]{32}/report\.pdf$`), "upload_url": h.AnyString, "expires_in": 3600,
	}).Object()
	if u, err := url.Parse(resp["upload_url"].(string)); err != nil || !strings.Contains(u.Path, "/staging/") {
		t.Fatalf("upload_url %v", resp["upload_url"])
	}
	w.Owner.Post(t, w.Path("/files/upload-url"), map[string]any{
		"filename": "x", "content_type": "a/b", "sha256": "ABC", "size": 1,
	}).Expect(http.StatusUnprocessableEntity).Match(h.Problem(422, "http_error", "sha256 must be a 64-character lowercase hex digest"))
	w.Owner.Post(t, w.Path("/files/upload-url"), map[string]any{
		"filename": "x", "content_type": "a/b", "sha256": digest("x"), "size": 1 << 40,
	}).Expect(http.StatusRequestEntityTooLarge)
}

func TestValidation(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Get(t, w.Path("/files/history")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/files/upload-urls"), map[string]any{"files": []any{}}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/files/move"), map[string]any{"source": "a", "destination": "b", "x": 1}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/files/tasks/t1/workspace/a.txt")).Expect(http.StatusNotFound).Match(h.Problem(404, "http_error", "File not found"))
}

func TestWhoCanReachTheFiles(t *testing.T) {
	w := h.NewWorkspace(t)
	upload(t, w, w.Owner, "shared.txt", "s")
	listing := map[string]any{"files": []any{file("shared.txt", 1, "text/plain")}, "directories": []any{}, "truncated": false}

	w.Member.Get(t, w.Path("/files")).Expect(http.StatusOK).Match(listing)
	key := w.APIKey(t)
	key.Get(t, w.Path("/files")).Expect(http.StatusOK).Match(listing)
	if got := key.Get(t, w.Path("/files/download/shared.txt")).Expect(http.StatusOK).Body; string(got) != "s" {
		t.Fatalf("api key download %q", got)
	}

	w.Outsider.Get(t, w.Path("/files")).Expect(http.StatusForbidden)
	w.Outsider.Get(t, w.Path("/files/download/shared.txt")).Expect(http.StatusForbidden)
	w.Outsider.Delete(t, w.Path("/files/shared.txt")).Expect(http.StatusForbidden)
	w.Outsider.Get(t, w.OutsiderPath("/files")).Expect(http.StatusOK).Match(map[string]any{"files": []any{}, "directories": []any{}, "truncated": false})
	w.Outsider.Get(t, w.OutsiderPath("/files/download/shared.txt")).Expect(http.StatusNotFound)
	w.Anonymous.Get(t, w.Path("/files")).Expect(http.StatusUnauthorized)
}

func TestSandboxesNeedTheInspectSecret(t *testing.T) {
	w := h.NewWorkspace(t)
	// The suite stack sets no AGENTAREA_SANDBOX_INSPECT_SECRET.
	w.Owner.Get(t, w.Path("/sandboxes")).Expect(http.StatusServiceUnavailable).
		Match(h.Problem(503, "http_error", "Sandbox inventory is not configured"))
	w.Outsider.Get(t, w.Path("/sandboxes")).Expect(http.StatusForbidden)
}
