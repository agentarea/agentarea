package main

import (
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/activationauth"
)

type ownRecorder struct {
	base  string
	infos []fs.FileInfo
}

func (r *ownRecorder) own(dir *os.File) error {
	info, err := dir.Stat()
	if err != nil {
		return err
	}
	r.infos = append(r.infos, info)
	return nil
}

func (r *ownRecorder) paths(t *testing.T) []string {
	t.Helper()
	var out []string
	for _, owned := range r.infos {
		err := filepath.WalkDir(r.base, func(path string, _ fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			info, err := os.Lstat(path)
			if err != nil {
				return err
			}
			if os.SameFile(info, owned) {
				rel, err := filepath.Rel(r.base, path)
				if err != nil {
					return err
				}
				out = append(out, filepath.ToSlash(rel))
			}
			return nil
		})
		if err != nil {
			t.Fatalf("walk %s: %v", r.base, err)
		}
	}
	return out
}

func openTestRoot(t *testing.T) (*os.Root, string) {
	t.Helper()
	base := t.TempDir()
	root, err := os.OpenRoot(base)
	if err != nil {
		t.Fatalf("open root: %v", err)
	}
	t.Cleanup(func() { _ = root.Close() })
	return root, base
}

func TestMkdirAllOwnedOwnsEveryCreatedComponentAndNoExistingOne(t *testing.T) {
	root, base := openTestRoot(t)
	if err := os.Mkdir(filepath.Join(base, "inputs"), 0o700); err != nil {
		t.Fatal(err)
	}
	recorder := &ownRecorder{base: base}

	if err := mkdirAllOwned(root, filepath.Join("inputs", "attachments", "deep"), recorder.own); err != nil {
		t.Fatalf("mkdirAllOwned: %v", err)
	}

	got := recorder.paths(t)
	want := []string{"inputs/attachments", "inputs/attachments/deep"}
	if !slices.Equal(got, want) {
		t.Fatalf("owned %v, want %v", got, want)
	}
	if info, err := os.Stat(filepath.Join(base, "inputs", "attachments", "deep")); err != nil || !info.IsDir() {
		t.Fatalf("inputs/attachments/deep was not created: %v", err)
	}
}

func TestMkdirAllOwnedLeavesAnExistingTreeAlone(t *testing.T) {
	root, base := openTestRoot(t)
	if err := os.MkdirAll(filepath.Join(base, "outputs", "reports"), 0o700); err != nil {
		t.Fatal(err)
	}
	recorder := &ownRecorder{base: base}

	if err := mkdirAllOwned(root, filepath.Join("outputs", "reports"), recorder.own); err != nil {
		t.Fatalf("mkdirAllOwned: %v", err)
	}

	if len(recorder.infos) != 0 {
		t.Fatalf("owned %v, want none", recorder.paths(t))
	}
}

func TestMkdirAllOwnedRefusesASymlinkedComponent(t *testing.T) {
	root, base := openTestRoot(t)
	if err := os.Mkdir(filepath.Join(base, "real"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("real", filepath.Join(base, "link")); err != nil {
		t.Fatal(err)
	}
	recorder := &ownRecorder{base: base}

	err := mkdirAllOwned(root, filepath.Join("link", "sub"), recorder.own)

	if err == nil {
		t.Fatal("mkdirAllOwned followed a symlinked component")
	}
	if _, statErr := os.Lstat(filepath.Join(base, "real", "sub")); !os.IsNotExist(statErr) {
		t.Fatalf("a directory was created through the symlink: %v", statErr)
	}
	if len(recorder.infos) != 0 {
		t.Fatalf("owned %v, want none", recorder.paths(t))
	}
}

func TestMkdirAllOwnedStopsWhenOwningFails(t *testing.T) {
	root, _ := openTestRoot(t)
	refused := fs.ErrPermission

	err := mkdirAllOwned(root, filepath.Join("outputs", "reports"), func(*os.File) error { return refused })

	if err == nil {
		t.Fatal("mkdirAllOwned ignored a failed chown")
	}
	if _, statErr := root.Lstat(filepath.Join("outputs", "reports")); !os.IsNotExist(statErr) {
		t.Fatalf("kept creating below a directory it could not own: %v", statErr)
	}
}

func TestFileWritesHandNestedParentsToTheSandboxUser(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("ownership is handed over only when the service runs as root")
	}
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	t.Setenv("AGENTAREA_SANDBOX_UID", "10001")
	t.Setenv("AGENTAREA_SANDBOX_GID", "10001")

	if w := putFile(t, "ws", "task-owned", "inputs/attachments/a.txt", []byte("a")); w.Code != http.StatusOK {
		t.Fatalf("put returned %d: %s", w.Code, w.Body.String())
	}
	if w := putFileStream(t, "ws", "task-owned", "outputs/report/b.bin", []byte("b")); w.Code != http.StatusOK {
		t.Fatalf("stream put returned %d: %s", w.Code, w.Body.String())
	}

	task := filepath.Join(workspaceRoot, "workspaces", "ws", "tasks", "task-owned")
	for _, rel := range []string{"inputs", "inputs/attachments", "outputs", "outputs/report"} {
		info, err := os.Lstat(filepath.Join(task, rel))
		if err != nil {
			t.Fatalf("stat %s: %v", rel, err)
		}
		st, ok := info.Sys().(*syscall.Stat_t)
		if !ok {
			t.Fatalf("stat %s carries no owner", rel)
		}
		if st.Uid != 10001 || st.Gid != 10001 {
			t.Fatalf("%s is owned by %d:%d, want 10001:10001", rel, st.Uid, st.Gid)
		}
	}
}
