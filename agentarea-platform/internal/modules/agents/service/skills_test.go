package service

import (
	"bytes"
	"context"
	"errors"
	"io"
	"iter"
	"net/http"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

type skillFakeBlob struct {
	blob.Store
	mu   sync.Mutex
	objs map[string][]byte
	puts int
}

func (b *skillFakeBlob) Put(_ context.Context, key string, body io.Reader, _ int64, _ blob.PutOptions) error {
	data, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	b.objs[key] = data
	b.puts++
	return nil
}

func (b *skillFakeBlob) Get(_ context.Context, key string) (io.ReadCloser, blob.Info, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	d, ok := b.objs[key]
	if !ok {
		return nil, blob.Info{}, blob.ErrNotFound
	}
	return io.NopCloser(bytes.NewReader(d)), blob.Info{Key: key, Size: int64(len(d))}, nil
}

func (b *skillFakeBlob) Stat(_ context.Context, key string) (blob.Info, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	d, ok := b.objs[key]
	if !ok {
		return blob.Info{}, blob.ErrNotFound
	}
	return blob.Info{Key: key, Size: int64(len(d))}, nil
}

func (b *skillFakeBlob) Delete(_ context.Context, key string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	delete(b.objs, key)
	return nil
}

func (b *skillFakeBlob) List(_ context.Context, prefix string) iter.Seq2[blob.Info, error] {
	b.mu.Lock()
	var infos []blob.Info
	for k, d := range b.objs {
		if strings.HasPrefix(k, prefix) {
			infos = append(infos, blob.Info{Key: k, Size: int64(len(d))})
		}
	}
	b.mu.Unlock()
	sort.Slice(infos, func(i, j int) bool { return infos[i].Key < infos[j].Key })
	return func(yield func(blob.Info, error) bool) {
		for _, i := range infos {
			if !yield(i, nil) {
				return
			}
		}
	}
}

func (b *skillFakeBlob) PresignGet(_ context.Context, key string, ttl time.Duration) (blob.Presigned, error) {
	return blob.Presigned{URL: "https://s3.test/" + key, TTL: ttl}, nil
}

type skillRoundTrip func(*http.Request) (*http.Response, error)

func (f skillRoundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func skillResp(code int, body string, h http.Header) *http.Response {
	if h == nil {
		h = http.Header{}
	}
	return &http.Response{StatusCode: code, Header: h, Body: io.NopCloser(strings.NewReader(body))}
}

func skillSetup(t *testing.T) (db.Database, *clientFakeGraph, *fakeAudit, *skillFakeBlob, *Skills, authn.Caller) {
	t.Helper()
	d, g, _, c := clientSetup(t)
	a := &fakeAudit{}
	s := New(Deps{DB: d, Graph: g, Audit: a, Now: func() time.Time { return time.Now().UTC() }})
	b := &skillFakeBlob{objs: map[string][]byte{}}
	return d, g, a, b, NewSkills(s, SkillPorts{Blob: b}), c
}

func skillActions(a *fakeAudit) string {
	var out []string
	for _, r := range a.recs {
		out = append(out, r.Action)
	}
	return strings.Join(out, ",")
}

func TestSkillsLifecycle(t *testing.T) {
	ctx := context.Background()
	_, g, a, b, k, c := skillSetup(t)
	v, err := k.CreateFromContent(ctx, c, "---\nname: PDF\ndescription: Reads PDFs\n---\n# PDF\nv1", nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(v.ID)
	if v.Name != "PDF" || v.Slug != "pdf" || *v.Description != "Reads PDFs" || v.SourceType != domain.SkillSourceContent ||
		!domain.SkillIsWorkspacePackage(*v.S3Path) || v.Content != nil {
		t.Fatalf("%+v", v)
	}
	if !g.objects[v.ID] {
		t.Error("creator was not granted the skill")
	}
	if _, ok := b.objs[*v.S3Path+"SKILL.md"]; !ok {
		t.Errorf("package objects %v", b.objs)
	}
	second, err := k.CreateFromContent(ctx, c, "# PDF\nother", nil, nil)
	if err != nil || second.Slug != "pdf-2" {
		t.Fatalf("slug %+v %v", second, err)
	}

	got, text, err := k.Content(ctx, c, id)
	if err != nil || got.ID != v.ID || !strings.Contains(text, "v1") {
		t.Fatalf("%q %v", text, err)
	}
	files, err := k.Files(ctx, c, id, true)
	if err != nil || len(files) != 1 || files[0].Path != "SKILL.md" || files[0].URL == nil {
		t.Fatalf("%+v %v", files, err)
	}
	if u, err := k.FileURL(ctx, c, id, "SKILL.md"); err != nil || !strings.HasPrefix(u, "https://s3.test/skills/") {
		t.Errorf("%s %v", u, err)
	}
	var fe *SkillFilesError
	if _, err := k.FileURL(ctx, c, id, "a/../b"); !errors.As(err, &fe) || fe.Msg != "Invalid skill file path: 'a/../b'" {
		t.Errorf("%v", err)
	}

	body := "---\nname: PDF\n---\n# PDF\nv2"
	name := "PDF tools"
	v2, err := k.Update(ctx, c, id, &name, nil, &body)
	if err != nil || v2.Name != "PDF tools" || *v2.S3Path == *v.S3Path {
		t.Fatalf("%+v %v", v2, err)
	}
	vs, err := k.Versions(ctx, c, id)
	if err != nil || len(vs) != 2 || vs[0].Reason != "create" || vs[1].Reason != "edit" || vs[0].Current || !vs[1].Current {
		t.Fatalf("%+v %v", vs, err)
	}
	back, err := k.Rollback(ctx, c, id, uuid.MustParse(vs[0].ID))
	if err != nil || *back.S3Path != *v.S3Path {
		t.Fatalf("%+v %v", back, err)
	}
	if _, err := k.Rollback(ctx, c, id, uuid.New()); !errors.Is(err, ErrSkillVersionNotFound) {
		t.Errorf("%v", err)
	}

	items, total, err := k.List(ctx, c, SkillListQuery{Limit: 10, IncludeCatalog: true})
	if err != nil || total != 2 || len(items) != 2 {
		t.Fatalf("%d %v", total, err)
	}
	search := "other"
	if _, total, _ := k.List(ctx, c, SkillListQuery{Limit: 10, Search: &search}); total != 0 {
		t.Errorf("search hits the body: %d", total)
	}

	a.recs = nil
	if err := k.Delete(ctx, c, id); err != nil {
		t.Fatal(err)
	}
	if skillActions(a) != "skill.delete" {
		t.Errorf("audit %s", skillActions(a))
	}
	if _, err := k.Get(ctx, c, id); err == nil {
		t.Error("deleted skill still reads")
	}
}

// Python's @audited records skill.update and skill.delete for a skill that
// is not there (audit/decorator.py records after any return); Go does not.
func TestSkillAuditOnlyForWhatHappened(t *testing.T) {
	ctx := context.Background()
	_, g, a, _, k, c := skillSetup(t)
	gone := uuid.New()
	g.objects[gone.String()] = true
	name := "x"
	if _, err := k.Update(ctx, c, gone, &name, nil, nil); !errors.Is(err, ErrSkillNotFound) {
		t.Errorf("update %v", err)
	}
	if err := k.Delete(ctx, c, gone); !errors.Is(err, ErrSkillNotFound) {
		t.Errorf("delete %v", err)
	}
	if len(a.recs) != 0 {
		t.Errorf("audited a non-event: %s", skillActions(a))
	}
}

func TestSkillCreateFromZipAndToolset(t *testing.T) {
	ctx := context.Background()
	_, _, _, _, k, c := skillSetup(t)
	ts := SkillToolset{K: k}
	sum, err := ts.CreateFromFiles(ctx, c, []api.SkillFileText{{Path: "SKILL.md", Text: "---\nname: Zipped\n---\nbody"}, {Path: "ref/a.txt", Text: "a"}},
		api.SkillCreate{SourceURL: ptr("https://example.test/x")})
	if err != nil || sum.Name != "Zipped" || sum.SourceType != domain.SkillSourceZip || *sum.SourceURL != "https://example.test/x" {
		t.Fatalf("%+v %v", sum, err)
	}
	files, err := ts.ListFiles(ctx, c, sum.ID, false)
	if err != nil || len(files) != 2 {
		t.Fatalf("%+v %v", files, err)
	}
	if data, err := ts.FileContent(ctx, c, sum.ID, "ref/a.txt"); err != nil || string(data) != "a" {
		t.Errorf("%q %v", data, err)
	}
	var ve *domain.SkillValueError
	if _, err := ts.ReplaceFiles(ctx, c, sum.ID, []api.SkillFileText{{Path: "a.txt", Text: "a"}}); !errors.As(err, &ve) || ve.Msg != "files must include a SKILL.md at the root" {
		t.Errorf("%v", err)
	}
	after, err := ts.ReplaceFiles(ctx, c, sum.ID, []api.SkillFileText{{Path: "SKILL.md", Text: "# New"}})
	if err != nil || after.Package == sum.Package {
		t.Errorf("%+v %v", after, err)
	}
	list, err := ts.List(ctx, c)
	if err != nil || len(list) != 1 {
		t.Errorf("%+v %v", list, err)
	}
	if _, err := k.CreateFromZip(ctx, c, []byte("nope"), nil, nil); !errors.As(err, &ve) {
		t.Errorf("not a zip: %v", err)
	}
}

func TestSkillMembersFlattenInMemberOrder(t *testing.T) {
	ctx := context.Background()
	_, _, _, _, k, c := skillSetup(t)
	mk := func(n string) string {
		v, err := k.CreateFromContent(ctx, c, "# "+n, nil, nil)
		if err != nil {
			t.Fatal(err)
		}
		return v.ID
	}
	parent, x, y, z := mk("P"), mk("X"), mk("Y"), mk("Z")
	pid := uuid.MustParse(parent)
	for i, m := range []domain.SkillMember{{ChildSkillID: z, Order: 0}, {ChildSkillID: x, Order: 1, Dependencies: []string{y}}, {ChildSkillID: y, Order: 2}} {
		m.ParentSkillID, m.IsRequired = parent, true
		if _, err := k.AddMember(ctx, c, m); err != nil {
			t.Fatal(i, err)
		}
	}
	var ve *domain.SkillValueError
	if _, err := k.AddMember(ctx, c, domain.SkillMember{ParentSkillID: parent, ChildSkillID: parent}); !errors.As(err, &ve) {
		t.Errorf("self: %v", err)
	}
	for range 5 {
		ids, err := k.Flatten(ctx, c, pid)
		if err != nil || strings.Join(ids, ",") != strings.Join([]string{z, y, x}, ",") {
			t.Fatalf("%v %v", ids, err)
		}
	}
	if err := k.RemoveMember(ctx, c, pid, uuid.MustParse(z)); err != nil {
		t.Fatal(err)
	}
	var nf *SkillMemberNotFoundError
	if err := k.RemoveMember(ctx, c, pid, uuid.MustParse(z)); !errors.As(err, &nf) {
		t.Errorf("%v", err)
	}
	if ms, err := k.Members(ctx, c, pid); err != nil || len(ms) != 2 {
		t.Errorf("%+v %v", ms, err)
	}
}

func TestSkillDownloadRepo(t *testing.T) {
	ctx := context.Background()
	k := &Skills{}
	if _, err := k.downloadRepo(ctx, "https://github.com/a/b"); err == nil {
		t.Fatal("no transport answers unwired")
	}
	var seen string
	cases := []struct {
		code   int
		header http.Header
		kind   domain.SkillGitHubErrorKind
		msg    string
	}{
		{404, nil, domain.SkillGitHubNotFound, "Repository not found. It may be private or the URL may be incorrect."},
		{429, nil, domain.SkillGitHubRateLimited, "GitHub throttled the request; retry later."},
		{403, nil, domain.SkillGitHubRateLimited, "GitHub API rate limit exceeded. Resets at unknown. Consider providing a GitHub token for higher limits."},
		{403, http.Header{"X-Ratelimit-Remaining": {"5"}}, domain.SkillGitHubOther, "Access forbidden: nope"},
		{500, nil, domain.SkillGitHubOther, "GitHub API error: 500 - nope"},
		{302, http.Header{"Location": {"https://evil.test/"}}, domain.SkillGitHubOther, "GitHub API error: 302 - nope"},
	}
	for _, tc := range cases {
		k.github = skillRoundTrip(func(r *http.Request) (*http.Response, error) {
			seen = r.URL.String()
			return skillResp(tc.code, "nope", tc.header), nil
		})
		var ge *domain.SkillGitHubError
		if _, err := k.downloadRepo(ctx, "https://github.com/acme/tools/tree/feat/x"); !errors.As(err, &ge) || ge.Kind != tc.kind || ge.Msg != tc.msg {
			t.Errorf("%d: %v", tc.code, err)
		}
	}
	if seen != "https://codeload.github.com/acme/tools/zip/feat" {
		t.Errorf("url %s", seen)
	}
	k.github = skillRoundTrip(func(r *http.Request) (*http.Response, error) { return skillResp(200, "zipbytes", nil), nil })
	if data, err := k.downloadRepo(ctx, "https://github.com/acme/tools"); err != nil || string(data) != "zipbytes" {
		t.Errorf("%q %v", data, err)
	}
	var ge *domain.SkillGitHubError
	if _, err := k.downloadRepo(ctx, "https://github.com/a$/b"); !errors.As(err, &ge) || ge.Msg != "Not a GitHub repository: a$/b" {
		t.Errorf("%v", err)
	}
	if skillQuote("feat/x y") != "feat%2Fx%20y" {
		t.Error(skillQuote("feat/x y"))
	}
}

func TestSkillGitHubCreateNeedsThePolicy(t *testing.T) {
	_, _, _, _, k, c := skillSetup(t)
	var ue *UnwiredError
	if _, err := k.CreateFromGitHub(context.Background(), c, "https://github.com/a/b", nil, nil); !errors.As(err, &ue) {
		t.Errorf("%v", err)
	}
}

func TestSkillMoveBodiesToPackages(t *testing.T) {
	ctx := context.Background()
	d, _, _, b, k, c := skillSetup(t)
	id := uuid.New()
	clientExec(t, d, c.Workspace, `INSERT INTO skills (id, name, slug, workspace_id, created_by, source_type, content) VALUES ($1, 'Old', $2, $3, 'u', 'content', $4)`,
		id, id.String(), c.Workspace.ID(), "# Old\nbody")
	moved, failed, err := k.MoveBodiesToPackages(ctx)
	if err != nil || failed != 0 || moved < 1 {
		t.Fatalf("%d %d %v", moved, failed, err)
	}
	var sk domain.Skill
	if err := d.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		var ok bool
		var err error
		sk, ok, err = skills().Get(ctx, s, id)
		if !ok && err == nil {
			err = errors.New("gone")
		}
		return err
	}); err != nil {
		t.Fatal(err)
	}
	if sk.Content != nil || sk.S3Path == nil || string(b.objs[*sk.S3Path+"SKILL.md"]) != "# Old\nbody" {
		t.Fatalf("%+v", sk)
	}
	if _, _, err := (&Skills{s: k.s}).MoveBodiesToPackages(ctx); err == nil {
		t.Error("no blob answers unwired")
	}
}

func TestListAndGetCountTheAgentsASkillIsAttachedTo(t *testing.T) {
	ctx := context.Background()
	d, _, _, _, k, c := skillSetup(t)
	r := RunSkills{K: k}
	used := newRunSkill(t, r, c, "---\nname: Used\ndescription: d\n---\nbody")
	idle := newRunSkill(t, r, c, "---\nname: Idle\ndescription: d\n---\nbody")
	runAgent(t, d, c, used)
	archived := runAgent(t, d, c, used)
	if err := d.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		_, err := s.Q().Exec(ctx, `UPDATE agents SET status = 'archived' WHERE id = $1`, archived)
		return err
	}); err != nil {
		t.Fatal(err)
	}

	views, _, err := k.List(ctx, c, SkillListQuery{Limit: 50})
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]int{}
	for _, v := range views {
		got[v.ID] = v.Agents
	}
	if got[used] != 1 || got[idle] != 0 {
		t.Fatalf("agent counts %v", got)
	}
	one, err := k.Get(ctx, c, uuid.MustParse(used))
	if err != nil {
		t.Fatal(err)
	}
	if one.Agents != 1 {
		t.Fatalf("get: %d agents", one.Agents)
	}
}

func TestListAndGetNumberEachSavedVersionOfASkill(t *testing.T) {
	ctx := context.Background()
	_, _, _, _, k, c := skillSetup(t)
	id := newRunSkill(t, RunSkills{K: k}, c, "---\nname: Draft\ndescription: d\n---\none")
	revision := func() int {
		t.Helper()
		v, err := k.Get(ctx, c, uuid.MustParse(id))
		if err != nil {
			t.Fatal(err)
		}
		return v.Revision
	}
	if got := revision(); got != 1 {
		t.Fatalf("created: revision %d", got)
	}
	body := "---\nname: Draft\ndescription: d\n---\ntwo"
	if _, err := k.Update(ctx, c, uuid.MustParse(id), nil, nil, &body); err != nil {
		t.Fatal(err)
	}
	if got := revision(); got != 2 {
		t.Fatalf("edited: revision %d", got)
	}
	views, _, err := k.List(ctx, c, SkillListQuery{Limit: 50})
	if err != nil {
		t.Fatal(err)
	}
	if len(views) != 1 || views[0].Revision != 2 {
		t.Fatalf("listed %+v", views)
	}
}
