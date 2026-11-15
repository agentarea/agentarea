package service

import (
	"context"
	"errors"
	"io"
	"net/http"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

func TestListWorkspaceHidesReservedAndAddsProjectFolders(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	f.put(t, "notes/a.md", "a")
	f.put(t, "tasks/t1/objects/x", "x")
	f.put(t, "staging/s/b.bin", "b")
	if _, err := f.svc.CreateDirectory(ctx, f.ws, user1, "empty/"); err != nil {
		t.Fatal(err)
	}
	l, err := f.svc.ListWorkspace(ctx, f.ws)
	if err != nil {
		t.Fatal(err)
	}
	if len(l.Files) != 1 || l.Files[0].Path != "notes/a.md" || l.Files[0].ContentType != "text/markdown" {
		t.Fatalf("files = %+v", l.Files)
	}
	if want := []string{"empty/", "projects/p1/"}; !reflect.DeepEqual(l.Directories, want) {
		t.Fatalf("directories = %v, want %v", l.Directories, want)
	}
	if l.Truncated {
		t.Fatal("truncated")
	}
}

func TestCreateDirectoryConflicts(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	f.put(t, "docs/readme.md", "r")
	cases := []struct {
		path   string
		status int
	}{
		{"/", http.StatusUnprocessableEntity},
		{"docs", http.StatusConflict},
		{"docs/readme.md", http.StatusConflict},
		{"docs/readme.md/sub", http.StatusConflict},
		{"projects", http.StatusConflict},
		{"apps/x", http.StatusForbidden},
		{"tasks/x", http.StatusUnprocessableEntity},
		{"a/../b", http.StatusUnprocessableEntity},
	}
	for _, c := range cases {
		_, err := f.svc.CreateDirectory(ctx, f.ws, user1, c.path)
		if err == nil {
			t.Fatalf("%q: no error", c.path)
		}
		if got := httpStatus(t, err); got != c.status {
			t.Fatalf("%q: status %d, want %d (%v)", c.path, got, c.status, err)
		}
	}
	dir, err := f.svc.CreateDirectory(ctx, f.ws, user1, "new/")
	if err != nil || dir != "new/" {
		t.Fatalf("dir = %q, %v", dir, err)
	}
	if got := f.events.actions(wsID, "new/"); !reflect.DeepEqual(got, []string{"created"}) {
		t.Fatalf("events = %v", got)
	}
}

func TestArchiveRestoreRoundTrip(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	f.put(t, "a/b.txt", "one")
	clean, archived, err := f.svc.Archive(ctx, f.ws, user1, "/a/b.txt")
	if err != nil {
		t.Fatal(err)
	}
	if clean != "a/b.txt" || archived != ".trash/20261112T093015.123456Z/a/b.txt" {
		t.Fatalf("archive = %q %q", clean, archived)
	}
	if f.store.Has("workspaces/" + wsID + "/a/b.txt") {
		t.Fatal("original still present")
	}
	if _, _, err := f.svc.Archive(ctx, f.ws, user1, "a/b.txt"); httpStatus(t, err) != http.StatusNotFound {
		t.Fatal(err)
	}
	if _, _, err := f.svc.Archive(ctx, f.ws, user1, "tasks/x"); httpStatus(t, err) != http.StatusBadRequest {
		t.Fatal(err)
	}
	f.put(t, "a/b.txt", "two")
	r, err := f.svc.Restore(ctx, f.ws, user1, archived)
	if err != nil {
		t.Fatal(err)
	}
	if r.Path != "a/b.txt" || r.RestoredFrom != archived || r.ArchivedCurrent == nil {
		t.Fatalf("restore = %+v", r)
	}
	data, _, err := f.svc.Artifacts().Get(ctx, wsID, "a/b.txt")
	if err != nil || string(data) != "one" {
		t.Fatalf("restored = %q, %v", data, err)
	}
	if _, err := f.svc.Restore(ctx, f.ws, user1, "a/b.txt"); httpStatus(t, err) != http.StatusBadRequest {
		t.Fatal(err)
	}
	if _, err := f.svc.Restore(ctx, f.ws, user1, archived); httpStatus(t, err) != http.StatusNotFound {
		t.Fatal(err)
	}
	if got := f.events.actions(wsID, "a/b.txt"); len(got) == 0 || got[0] != "archived" {
		t.Fatalf("events = %v", got)
	}
}

func TestMoveFileAndFolder(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	f.put(t, "src/a.txt", "a")
	f.put(t, "src/deep/b.txt", "b")
	f.put(t, "taken.txt", "t")
	if _, err := f.svc.Move(ctx, f.ws, user1, "src", "src/inner"); httpStatus(t, err) != http.StatusUnprocessableEntity {
		t.Fatal(err)
	}
	if _, err := f.svc.Move(ctx, f.ws, user1, "src", "taken.txt"); httpStatus(t, err) != http.StatusConflict {
		t.Fatal(err)
	}
	if _, err := f.svc.Move(ctx, f.ws, user1, "nothing", "else"); httpStatus(t, err) != http.StatusNotFound {
		t.Fatal(err)
	}
	m, err := f.svc.Move(ctx, f.ws, user1, "src/", "dst")
	if err != nil || m.Count != 2 || m.Source != "src" || m.Destination != "dst" {
		t.Fatalf("move = %+v, %v", m, err)
	}
	if !f.store.Has("workspaces/"+wsID+"/dst/deep/b.txt") || f.store.Has("workspaces/"+wsID+"/src/a.txt") {
		t.Fatal("folder not moved")
	}
	m, err = f.svc.Move(ctx, f.ws, user1, "dst/a.txt", "a2.txt")
	if err != nil || m.Count != 1 {
		t.Fatalf("move file = %+v, %v", m, err)
	}
	if got := f.events.actions(wsID, "a2.txt"); !reflect.DeepEqual(got, []string{"moved", "moved"}) {
		t.Fatalf("events = %v", got)
	}
}

func TestHistoryFollowsMoves(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	f.put(t, "a.txt", "a")
	f.put(t, "dir/b.txt", "b")
	f.events.seed(wsID, domain.ArtifactEvent{Path: "a.txt", Action: domain.ActionCreated, ActorType: domain.ActorUser, CreatedBy: user1})
	f.events.seed(wsID, domain.ArtifactEvent{Path: "dir/b.txt", Action: domain.ActionCreated, ActorType: domain.ActorUser, CreatedBy: user1})
	if _, err := f.svc.Move(ctx, f.ws, user1, "a.txt", "c.txt"); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Move(ctx, f.ws, user1, "dir", "moved"); err != nil {
		t.Fatal(err)
	}
	if got := f.events.actions(wsID, "c.txt"); !reflect.DeepEqual(got, []string{"created", "moved"}) {
		t.Fatalf("c.txt events = %v", got)
	}
	if got := f.events.actions(wsID, "moved/b.txt"); !reflect.DeepEqual(got, []string{"created", "moved"}) {
		t.Fatalf("moved/b.txt events = %v", got)
	}
	if got := f.events.actions(wsID, "a.txt"); got != nil {
		t.Fatalf("a.txt keeps events %v", got)
	}
}

func TestFolderMoveRollsBackOnFailure(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	for _, p := range []string{"src/1.txt", "src/2.txt", "src/3.txt"} {
		f.put(t, p, p)
	}
	boom := errors.New("copy failed")
	f.store.FailCopy = func(src, _ string) error {
		if strings.HasSuffix(src, "/src/3.txt") {
			return boom
		}
		return nil
	}
	if _, err := f.svc.Move(ctx, f.ws, user1, "src", "dst"); !errors.Is(err, boom) {
		t.Fatalf("move = %v", err)
	}
	for _, p := range []string{"1.txt", "2.txt", "3.txt"} {
		if !f.store.Has("workspaces/"+wsID+"/src/"+p) || f.store.Has("workspaces/"+wsID+"/dst/"+p) {
			t.Fatalf("%s: folder split after a failed move", p)
		}
	}
	if got := f.events.actions(wsID, "dst/1.txt"); got != nil {
		t.Fatalf("events recorded for an aborted move: %v", got)
	}
}

func TestPlanUploads(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	f.put(t, "same.txt", "same")
	ct := "text/plain"
	out, err := f.svc.PlanUploads(ctx, f.ws, user1, []api.UploadEntry{
		{Path: "same.txt", SHA256: sha("same")},
		{Path: "new.txt", SHA256: sha("new"), ContentType: &ct},
		{Path: "bad.txt", SHA256: "nope"},
		{Path: "../x", SHA256: sha("x")},
		{Path: "apps/x", SHA256: sha("x")},
	})
	if err != nil {
		t.Fatal(err)
	}
	got := []string{}
	for _, p := range out {
		got = append(got, p.Status)
	}
	if want := []string{"unchanged", "upload", "error", "error", "error"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("statuses = %v", got)
	}
	up := out[1]
	if *up.Method != "PUT" || *up.ExpiresIn != 600 || up.Headers["x-amz-meta-sha256"] != sha("new") || up.Headers["Content-Type"] != ct {
		t.Fatalf("upload = %+v", up)
	}
	if got := f.events.actions(wsID, "new.txt"); !reflect.DeepEqual(got, []string{"created"}) {
		t.Fatalf("events at mint time = %v", got)
	}
}

func TestPresignAttachment(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	p, err := f.svc.PresignAttachment(ctx, f.ws, "dir/report.pdf", "application/pdf", sha("r"), 10)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(p.Ref, "staging/") || !strings.HasSuffix(p.Ref, "/report.pdf") || p.ExpiresIn != 3600 {
		t.Fatalf("presign = %+v", p)
	}
	for _, c := range []struct {
		sha    string
		size   int64
		status int
	}{{"ABC", 1, 422}, {sha("r"), -1, 422}, {sha("r"), MaxAttachmentBytes + 1, 413}} {
		if _, err := f.svc.PresignAttachment(ctx, f.ws, "x", "a/b", c.sha, c.size); httpStatus(t, err) != c.status {
			t.Fatalf("%+v: %v", c, err)
		}
	}
}

func TestDownloadVerifiesAndMapsTo404(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	f.put(t, "ok.txt", "hello")
	v, err := f.svc.Download(ctx, f.ws, "ok.txt")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(v.Body)
	_ = v.Body.Close()
	if string(body) != "hello" || v.Size != 5 || v.ContentType != "text/plain" {
		t.Fatalf("download = %q %+v", body, v)
	}
	if err := f.store.Put(ctx, "workspaces/"+wsID+"/raw.bin", strings.NewReader("raw"), 3, blobOpts("")); err != nil {
		t.Fatal(err)
	}
	v, err = f.svc.Download(ctx, f.ws, "raw.bin")
	if err != nil {
		t.Fatalf("an object without a digest is served: %v", err)
	}
	body, _ = io.ReadAll(v.Body)
	_ = v.Body.Close()
	if string(body) != "raw" {
		t.Fatalf("raw = %q", body)
	}
	bad := blob.PutOptions{Metadata: map[string]string{"sha256": sha("other")}}
	if err := f.store.Put(ctx, "workspaces/"+wsID+"/bad.bin", strings.NewReader("bad"), 3, bad); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{"bad.bin", "missing", ".trash/x", "staging/a", "tasks/t/other", "a/../b", ""} {
		if _, err := f.svc.Download(ctx, f.ws, p); httpStatus(t, err) != http.StatusNotFound {
			t.Fatalf("%q: %v", p, err)
		}
	}
}

func TestFileURL(t *testing.T) {
	f := newFixture(t, Deps{APIURL: "https://api.test/"})
	ctx := context.Background()
	f.put(t, "my dir/ü.txt", "x")
	u, err := f.svc.FileURL(ctx, f.ws, "my dir/ü.txt")
	if err != nil {
		t.Fatal(err)
	}
	if want := "https://api.test/v1/workspaces/acme/files/download/my%20dir/%C3%BC.txt"; u != want {
		t.Fatalf("url = %s", u)
	}
	if _, err := f.svc.FileURL(ctx, f.ws, "tasks/x/y"); httpStatus(t, err) != http.StatusNotFound {
		t.Fatal(err)
	}
}

func TestHistoryNewestFirst(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	if _, err := f.svc.Artifacts().Put(ctx, wsID, "h.txt", []byte("1"), "", userActor(user1)); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Artifacts().Put(ctx, wsID, "h.txt", []byte("2"), "", userActor(user1)); err != nil {
		t.Fatal(err)
	}
	clean, evs, err := f.svc.History(ctx, f.ws, "/h.txt")
	if err != nil || clean != "h.txt" || len(evs) != 2 || evs[0].Action != "modified" || evs[1].Action != "created" {
		t.Fatalf("history = %q %+v %v", clean, evs, err)
	}
	if evs[0].CreatedBy != user1 || evs[0].ActorType != "user" {
		t.Fatalf("actor = %+v", evs[0])
	}
}

func TestFilesPortForProjects(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	files := f.svc.Files()
	f.put(t, "projects/p1/a.txt", "a")
	list, err := files.List(ctx, f.ws, "projects/p1/")
	if err != nil || len(list) != 1 || list[0].Path != "projects/p1/a.txt" {
		t.Fatalf("list = %+v, %v", list, err)
	}
	got, err := files.Get(ctx, f.ws, "projects/p1/a.txt")
	if err != nil || string(got.Data) != "a" {
		t.Fatalf("get = %+v, %v", got, err)
	}
	if h, ok, err := files.Head(ctx, f.ws, "projects/p1/a.txt"); err != nil || !ok || h.Size != 1 {
		t.Fatalf("head = %+v %v %v", h, ok, err)
	}
	if err := files.Delete(ctx, f.ws, user1, "projects/p1/a.txt"); err != nil {
		t.Fatal(err)
	}
	if ok, _ := files.Exists(ctx, f.ws, "projects/p1/a.txt"); ok {
		t.Fatal("still exists")
	}
	if _, ok, err := files.Head(ctx, f.ws, "projects/p1/a.txt"); err != nil || ok {
		t.Fatalf("head after delete = %v %v", ok, err)
	}
	if _, err := files.Get(ctx, f.ws, "projects/p1/a.txt"); err == nil {
		t.Fatal("get after delete")
	}
}
