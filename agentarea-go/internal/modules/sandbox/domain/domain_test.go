package domain

import (
	"errors"
	"reflect"
	"strings"
	"testing"
)

func TestNormalizeWorkspacePath(t *testing.T) {
	for _, ok := range []string{"a", "a/b.txt", ".hidden/x"} {
		if got, err := NormalizeWorkspacePath(ok); err != nil || got != ok {
			t.Fatalf("%q: %q %v", ok, got, err)
		}
	}
	for p, msg := range map[string]string{
		"":       "workspace path must be a non-empty string",
		"/a":     "workspace path escapes task root: '/a'",
		"a/../b": "workspace path escapes task root: 'a/../b'",
		"a//b":   "workspace path is not canonical: 'a//b'",
		"a/./b":  "workspace path is not canonical: 'a/./b'",
		"a\nb":   `workspace path is not canonical POSIX: 'a\nb'`,
		`a\b`:    `workspace path is not canonical POSIX: 'a\\b'`,
	} {
		_, err := NormalizeWorkspacePath(p)
		if err == nil || err.Error() != msg || !IsValidation(err) {
			t.Fatalf("%q: %v, want %s", p, err, msg)
		}
	}
}

func TestResolveWritePath(t *testing.T) {
	if got, _ := ResolveWritePath("", "dir/f.txt"); got != "f.txt" {
		t.Fatalf("filename = %q", got)
	}
	if got, _ := ResolveWritePath("", ""); got != "unnamed" {
		t.Fatalf("empty = %q", got)
	}
	if _, err := ResolveWritePath("tasks/x", ""); err == nil || err.Error() != "'tasks/x' is a reserved prefix and cannot be written directly" {
		t.Fatal(err)
	}
	_, err := ResolveWritePath("apps/x", "")
	var ro *ReadOnlyError
	if !errors.As(err, &ro) {
		t.Fatalf("apps = %v", err)
	}
	if _, err := ResolveWritePath(strings.Repeat("a", MaxWritePathBytes+1), ""); err == nil {
		t.Fatal("over-long path accepted")
	}
}

func TestTaskWorkspacePath(t *testing.T) {
	id, rel, ok, err := TaskWorkspacePath("/tasks/t1/workspace/out/a.txt")
	if !ok || err != nil || id != "t1" || rel != "out/a.txt" {
		t.Fatalf("= %q %q %v %v", id, rel, ok, err)
	}
	if _, _, ok, _ := TaskWorkspacePath("tasks/t1/objects/x"); ok {
		t.Fatal("objects parsed as workspace")
	}
	if _, _, ok, err := TaskWorkspacePath("tasks/t1/workspace//a/b"); !ok || err == nil {
		t.Fatal("non-canonical accepted")
	}
}

func TestPathHelpers(t *testing.T) {
	if !IsReservedPath("/.trash/x") || IsReservedPath("trash/x") || !IsReadOnlyPath("apps") {
		t.Fatal("prefix checks")
	}
	if got := Parents("a/b/c"); !reflect.DeepEqual(got, []string{"a/b", "a"}) {
		t.Fatalf("parents = %v", got)
	}
	if PosixName("a/b/") != "b" || PosixName("/") != "" {
		t.Fatal("posix name")
	}
	if got := PyRepr("it's"); got != `"it's"` {
		t.Fatalf("repr = %s", got)
	}
	if got := PyRepr("é\x01"); got != `'é\x01'` {
		t.Fatalf("repr = %s", got)
	}
}

func TestContentTypes(t *testing.T) {
	for p, want := range map[string]string{
		"a.txt": "text/plain", "b.MD": "text/markdown", "c.tar.gz": "application/x-tar", "d.svgz": "image/svg+xml",
		"e.json": "application/json", "noext": "application/octet-stream", "f.gz": "application/octet-stream",
	} {
		if got := ContentTypeOf(p); got != want {
			t.Fatalf("%s: %s, want %s", p, got, want)
		}
	}
}
