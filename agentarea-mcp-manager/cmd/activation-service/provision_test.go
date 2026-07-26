package main

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
)

// newInputObjectServer serves a single object body and counts GET hits so a
// test can assert the marker prevents a second fetch.
func newInputObjectServer(t *testing.T, body []byte) (*httptest.Server, *int32) {
	t.Helper()
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		atomic.AddInt32(&hits, 1)
		_, _ = w.Write(body)
	}))
	t.Cleanup(server.Close)
	return server, &hits
}

func TestProvisionTaskInputsWritesInputToRelativePath(t *testing.T) {
	body := []byte("revenue,margin\n10,3\n")
	server, hits := newInputObjectServer(t, body)
	t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", server.URL)
	t.Setenv("SANDBOX_WORKSPACE_S3_BUCKET", "artifacts")

	workspaceDir := t.TempDir()
	sum := sha256.Sum256(body)
	refs := []InputRef{{
		RelativePath: "inputs/attachments/report.csv",
		URL:          server.URL + "/artifacts/workspaces/w/tasks/t/objects/" + hex.EncodeToString(sum[:]),
		ObjectURI:    "s3://artifacts/workspaces/w/tasks/t/objects/" + hex.EncodeToString(sum[:]),
		SHA256:       hex.EncodeToString(sum[:]),
		Size:         int64(len(body)),
	}}

	if err := provisionTaskInputs(workspaceDir, refs); err != nil {
		t.Fatalf("provisionTaskInputs returned error: %v", err)
	}

	written, err := os.ReadFile(filepath.Join(workspaceDir, "inputs", "attachments", "report.csv"))
	if err != nil {
		t.Fatalf("input file was not written: %v", err)
	}
	if string(written) != string(body) {
		t.Fatalf("input content mismatch: got %q want %q", written, body)
	}
	if got := atomic.LoadInt32(hits); got != 1 {
		t.Fatalf("expected exactly one object fetch, got %d", got)
	}
	if _, err := os.Stat(filepath.Join(workspaceDir, ".agentarea", ".inputs_provisioned")); err != nil {
		t.Fatalf("provisioned marker was not created: %v", err)
	}
}

func TestProvisionTaskInputsSkipsAfterMarker(t *testing.T) {
	body := []byte("hello inputs")
	server, hits := newInputObjectServer(t, body)
	t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", server.URL)
	t.Setenv("SANDBOX_WORKSPACE_S3_BUCKET", "artifacts")

	workspaceDir := t.TempDir()
	sum := sha256.Sum256(body)
	refs := []InputRef{{
		RelativePath: "inputs/attachments/notes.txt",
		URL:          server.URL + "/artifacts/workspaces/w/tasks/t/objects/" + hex.EncodeToString(sum[:]),
		ObjectURI:    "s3://artifacts/workspaces/w/tasks/t/objects/" + hex.EncodeToString(sum[:]),
		SHA256:       hex.EncodeToString(sum[:]),
		Size:         int64(len(body)),
	}}

	if err := provisionTaskInputs(workspaceDir, refs); err != nil {
		t.Fatalf("first provisionTaskInputs returned error: %v", err)
	}
	if err := provisionTaskInputs(workspaceDir, refs); err != nil {
		t.Fatalf("second provisionTaskInputs returned error: %v", err)
	}
	if got := atomic.LoadInt32(hits); got != 1 {
		t.Fatalf("marker did not prevent re-fetch: object fetched %d times", got)
	}
}

func TestProvisionTaskInputsRejectsOutOfBucketObjectURI(t *testing.T) {
	body := []byte("payload")
	server, hits := newInputObjectServer(t, body)
	t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", server.URL)
	t.Setenv("SANDBOX_WORKSPACE_S3_BUCKET", "artifacts")

	workspaceDir := t.TempDir()
	refs := []InputRef{{
		RelativePath: "inputs/attachments/report.csv",
		URL:          server.URL + "/artifacts/workspaces/w/tasks/t/objects/deadbeef",
		ObjectURI:    "s3://other-bucket/workspaces/w/tasks/t/objects/deadbeef",
	}}

	if err := provisionTaskInputs(workspaceDir, refs); err == nil {
		t.Fatal("expected error for out-of-bucket object_uri, got nil")
	}
	if got := atomic.LoadInt32(hits); got != 0 {
		t.Fatalf("out-of-bucket ref must be rejected before any fetch, got %d fetches", got)
	}
	if _, err := os.Stat(filepath.Join(workspaceDir, "inputs")); !os.IsNotExist(err) {
		t.Fatalf("no input should have been written for a rejected ref")
	}
}

func TestProvisionTaskInputsRejectsTraversalPath(t *testing.T) {
	body := []byte("payload")
	server, _ := newInputObjectServer(t, body)
	t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", server.URL)
	t.Setenv("SANDBOX_WORKSPACE_S3_BUCKET", "artifacts")

	workspaceDir := t.TempDir()
	sum := sha256.Sum256(body)
	refs := []InputRef{{
		RelativePath: "../escape.txt",
		URL:          server.URL + "/artifacts/workspaces/w/tasks/t/objects/" + hex.EncodeToString(sum[:]),
		ObjectURI:    "s3://artifacts/workspaces/w/tasks/t/objects/" + hex.EncodeToString(sum[:]),
	}}

	if err := provisionTaskInputs(workspaceDir, refs); err == nil {
		t.Fatal("expected error for traversal relative_path, got nil")
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(workspaceDir), "escape.txt")); !os.IsNotExist(err) {
		t.Fatal("traversal path must not write outside the workspace")
	}
}
