package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"slices"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	govapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

type catalogFakeItems struct {
	CatalogItems
	items     map[string]catalogapi.CatalogItem
	installed map[string]*string
	folder    catalogapi.GitHubFolder
	reads     []string
}

func newCatalogFakeItems(items ...catalogapi.CatalogItem) *catalogFakeItems {
	f := &catalogFakeItems{items: map[string]catalogapi.CatalogItem{}, installed: map[string]*string{}}
	for _, it := range items {
		f.items[it.ID] = it
	}
	return f
}

func (f *catalogFakeItems) SkillItem(_ context.Context, _ scope.Workspace, id string) (catalogapi.CatalogItem, bool, error) {
	it, ok := f.items[id]
	it.InstalledVersion = f.installed[id]
	return it, ok, nil
}

func (f *catalogFakeItems) SkillVersions(_ context.Context, _ scope.Workspace, ids []string) (map[string]catalogapi.ItemVersions, error) {
	out := map[string]catalogapi.ItemVersions{}
	for _, id := range ids {
		if it, ok := f.items[id]; ok {
			out[id] = catalogapi.ItemVersions{Current: it.Version, Installed: f.installed[id]}
		}
	}
	return out, nil
}

func (f *catalogFakeItems) MarkInstalled(_ context.Context, _ db.Session, itemID, _ string, version *string) error {
	f.installed[itemID] = version
	return nil
}

func (f *catalogFakeItems) Folder(_ context.Context, token, repo, folder string, _, _ *string) (catalogapi.GitHubFolder, error) {
	f.reads = append(f.reads, token+"@"+repo+"/"+folder)
	if f.folder.Commit == "" {
		return catalogapi.GitHubFolder{}, &catalogapi.FolderError{Msg: "The skill was removed upstream", NotFound: true}
	}
	return f.folder, nil
}

func (f *catalogFakeItems) bump(id, version, body string) {
	it := f.items[id]
	it.Version = &version
	it.Spec, _ = json.Marshal(map[string]any{"content": body})
	f.items[id] = it
}

func helperBody(v string) string {
	return "---\nname: Catalog helper\ndescription: Helps\n---\n" + v
}

type catalogFixture struct {
	d     db.Database
	g     *clientFakeGraph
	b     *skillFakeBlob
	k     *Skills
	c     authn.Caller
	items *catalogFakeItems
}

func catalogSetup(t *testing.T) catalogFixture {
	t.Helper()
	d, g, _, b, k, c := skillSetup(t)
	items := newCatalogFakeItems()
	k.items, k.policy = items, runFakePolicy{}
	k.UseCatalog(CatalogSkills{K: k})
	return catalogFixture{d: d, g: g, b: b, k: k, c: c, items: items}
}

func installHelper(t *testing.T, k *Skills, c authn.Caller, items *catalogFakeItems, body string) (catalogapi.CatalogItem, SkillView) {
	t.Helper()
	item := catalogSkillItem(map[string]any{"content": body})
	items.items[item.ID] = item
	v, err := k.Install(context.Background(), c, uuid.MustParse(item.ID))
	if err != nil {
		t.Fatal(err)
	}
	return item, v
}

func skillMD(t *testing.T, k *Skills, c authn.Caller, id string) string {
	t.Helper()
	_, text, err := k.Content(context.Background(), c, uuid.MustParse(id))
	if err != nil {
		t.Fatal(err)
	}
	return text
}

func TestUpdateFromCatalogMovesAnInstallToItsItemsCurrentVersion(t *testing.T) {
	ctx := context.Background()
	f := catalogSetup(t)
	k, c, items := f.k, f.c, f.items
	cat := CatalogSkills{K: k}
	item, v := installHelper(t, k, c, items, helperBody("v1"))
	id := uuid.MustParse(v.ID)

	same, ok, err := cat.Update(ctx, c, id, false)
	if err != nil || !ok || *same.S3Path != *v.S3Path {
		t.Fatalf("up to date: %+v %v %v", same.Skill, ok, err)
	}
	items.bump(item.ID, "2.0.0", helperBody("v2"))
	updated, ok, err := cat.Update(ctx, c, id, false)
	if err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	if *updated.S3Path == *v.S3Path || !domain.SkillIsCatalogPackage(*updated.S3Path) || !strings.HasSuffix(skillMD(t, k, c, v.ID), "v2") {
		t.Fatalf("update: %+v", updated.Skill)
	}
	if got := items.installed[item.ID]; got == nil || *got != "2.0.0" {
		t.Fatalf("install pin %v", got)
	}
	versions, err := k.Versions(ctx, c, id)
	if err != nil {
		t.Fatal(err)
	}
	last := versions[len(versions)-1]
	if last.Reason != "update" || last.CatalogVersion == nil || *last.CatalogVersion != "2.0.0" || !last.Current {
		t.Fatalf("versions %+v", versions)
	}

	edited := helperBody("mine")
	if _, err := k.Update(ctx, c, id, nil, nil, &edited); err != nil {
		t.Fatal(err)
	}
	items.bump(item.ID, "3.0.0", helperBody("v3"))
	var customized *SkillCustomizedError
	if _, _, err := cat.Update(ctx, c, id, false); !errors.As(err, &customized) {
		t.Fatalf("a customized skill was updated: %v", err)
	}
	if !strings.HasSuffix(skillMD(t, k, c, v.ID), "mine") {
		t.Fatal("the refused update replaced the edit")
	}
	if _, _, err := cat.Update(ctx, c, id, true); err != nil || !strings.HasSuffix(skillMD(t, k, c, v.ID), "v3") {
		t.Fatalf("discarding the edit: %v", err)
	}

	own, err := k.CreateFromContent(ctx, c, "---\nname: Own\ndescription: Mine\n---\nbody", nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	var notFrom *SkillNotFromCatalogError
	if _, _, err := cat.Update(ctx, c, uuid.MustParse(own.ID), false); !errors.As(err, &notFrom) {
		t.Fatalf("a workspace skill: %v", err)
	}
	delete(items.items, item.ID)
	if _, _, err := cat.Update(ctx, c, id, false); !errors.As(err, &notFrom) {
		t.Fatalf("an install whose item is gone: %v", err)
	}
	if _, ok, err := cat.Update(ctx, c, uuid.New(), false); ok || err != nil {
		t.Fatalf("no such skill: %v %v", ok, err)
	}
}

func TestUpdateAllUpdatesWhatMovedOnAndReportsWhatWasEdited(t *testing.T) {
	ctx := context.Background()
	f := catalogSetup(t)
	k, c, items := f.k, f.c, f.items
	cat := CatalogSkills{K: k}
	installHelper(t, k, c, items, helperBody("current"))
	moved, mv := installHelper(t, k, c, items, helperBody("old"))
	edited, ev := installHelper(t, k, c, items, helperBody("old"))
	mine := helperBody("mine")
	if _, err := k.Update(ctx, c, uuid.MustParse(ev.ID), nil, nil, &mine); err != nil {
		t.Fatal(err)
	}
	items.bump(moved.ID, "2", helperBody("new"))
	items.bump(edited.ID, "2", helperBody("new"))

	results, err := cat.UpdateAll(ctx, c)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]string{}
	for _, r := range results {
		got[r.SkillID] = r.Status
	}
	if len(results) != 2 || got[mv.ID] != "updated" || got[ev.ID] != "customized" {
		t.Fatalf("results %+v", results)
	}
	if !strings.HasSuffix(skillMD(t, k, c, mv.ID), "new") || !strings.HasSuffix(skillMD(t, k, c, ev.ID), "mine") {
		t.Fatal("update-all moved the wrong skills")
	}
}

func TestRollbackToAnInstalledVersionRepinsTheInstall(t *testing.T) {
	ctx := context.Background()
	f := catalogSetup(t)
	k, c, items := f.k, f.c, f.items
	item, v := installHelper(t, k, c, items, helperBody("v1"))
	id := uuid.MustParse(v.ID)
	items.bump(item.ID, "2.0.0", helperBody("v2"))
	if _, _, err := (CatalogSkills{K: k}).Update(ctx, c, id, false); err != nil {
		t.Fatal(err)
	}
	versions, err := k.Versions(ctx, c, id)
	if err != nil {
		t.Fatal(err)
	}
	back, err := k.Rollback(ctx, c, id, uuid.MustParse(versions[0].ID))
	if err != nil {
		t.Fatal(err)
	}
	if *back.S3Path != *v.S3Path || items.installed[item.ID] == nil || *items.installed[item.ID] != "1.2.0" {
		t.Fatalf("rollback %+v, pin %v", back.Skill, items.installed[item.ID])
	}
}

func (f catalogFixture) insertPrePackage(t *testing.T, name, body string, itemID *string) string {
	t.Helper()
	id := uuid.New()
	f.g.objects[id.String()] = true
	clientExec(t, f.d, f.c.Workspace, `INSERT INTO skills (id, name, slug, workspace_id, created_by, source_type, content, registry_item_id)
		VALUES ($1, $2, $3, $4, 'u', 'content', $5, $6)`, id, name, id.String(), f.c.Workspace.ID(), body, itemID)
	return id.String()
}

func jobResults(results []SkillJobResult, ws string) map[string]SkillJobResult {
	out := map[string]SkillJobResult{}
	for _, r := range results {
		if r.WorkspaceID == ws {
			out[r.SkillID] = r
		}
	}
	return out
}

func TestRepinAllRepinsPrePackageInstallsNobodyEdited(t *testing.T) {
	ctx := context.Background()
	f := catalogSetup(t)
	k, c, items := f.k, f.c, f.items
	cat := CatalogSkills{K: k}
	ws := c.Workspace.ID()
	asGiven := catalogSkillItem(map[string]any{"content": helperBody("given")})
	edited := catalogSkillItem(map[string]any{"content": helperBody("given")})
	noBody := catalogSkillItem(map[string]any{"source_url": "https://x"})
	stubDesc := "Reads and writes PDF files"
	replaced := catalogSkillItem(map[string]any{"source": map[string]any{"type": "github", "repo": "anthropics/skills", "path": "document-skills/pdf"}})
	replaced.Name, replaced.Description = "pdf--anthropics", &stubDesc
	sum := sha256.Sum256([]byte(helperBody("digest")))
	digested := catalogSkillItem(map[string]any{"source": map[string]any{"type": "github", "repo": "o/r"}, "replaced_body_sha256": hex.EncodeToString(sum[:])})
	for _, it := range []catalogapi.CatalogItem{asGiven, edited, noBody, replaced, digested} {
		items.items[it.ID] = it
	}
	gone := uuid.NewString()
	ids := map[string]string{
		"asGiven":  f.insertPrePackage(t, "Given", helperBody("given"), &asGiven.ID),
		"edited":   f.insertPrePackage(t, "Edited", helperBody("changed"), &edited.ID),
		"noBody":   f.insertPrePackage(t, "No body", helperBody("x"), &noBody.ID),
		"replaced": f.insertPrePackage(t, "pdf--anthropics", stubBody, &replaced.ID),
		"digested": f.insertPrePackage(t, "Digested", helperBody("digest"), &digested.ID),
		"gone":     f.insertPrePackage(t, "Gone", helperBody("x"), &gone),
		"own":      f.insertPrePackage(t, "Own", helperBody("x"), nil),
	}
	_, pinned := installHelper(t, k, c, items, helperBody("pinned"))
	items.folder = catalogapi.GitHubFolder{Commit: "c1", TreeSHA: "t1", Files: map[string][]byte{domain.SkillManifest: []byte(helperBody("original"))}}

	dry, err := cat.RepinAll(ctx, true)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"asGiven": "would_repin", "edited": "edited", "noBody": "unverified", "replaced": "would_repin",
		"digested": "would_repin", "gone": "gone"}
	got := jobResults(dry, ws)
	for key, status := range want {
		if got[ids[key]].Status != status {
			t.Errorf("dry run %s: %+v, want %s", key, got[ids[key]], status)
		}
	}
	if _, listed := got[ids["own"]]; listed || got[pinned.ID].Status != "pinned" {
		t.Errorf("own %+v, pinned %+v", got[ids["own"]], got[pinned.ID])
	}
	if e := got[ids["gone"]].Error; e == nil || *e != "its catalog item is no longer listed" {
		t.Errorf("gone: %v", e)
	}

	done, err := cat.RepinAll(ctx, false)
	if err != nil {
		t.Fatal(err)
	}
	got = jobResults(done, ws)
	for _, key := range []string{"asGiven", "replaced", "digested"} {
		if got[ids[key]].Status != "repinned" {
			t.Errorf("%s: %+v", key, got[ids[key]])
		}
	}
	if !strings.HasSuffix(skillMD(t, k, c, ids["asGiven"]), "given") || !strings.HasSuffix(skillMD(t, k, c, ids["replaced"]), "original") {
		t.Error("repinned skills do not read their item's package")
	}
	versions, err := k.Versions(ctx, c, uuid.MustParse(ids["asGiven"]))
	if err != nil || versions[len(versions)-1].Reason != "repin" {
		t.Fatalf("versions %+v %v", versions, err)
	}
	if got[ids["edited"]].Status != "edited" || !strings.HasSuffix(skillMD(t, k, c, ids["edited"]), "changed") {
		t.Error("the edited install moved")
	}

	again, err := cat.RepinAll(ctx, false)
	if err != nil {
		t.Fatal(err)
	}
	if s := jobResults(again, ws)[ids["asGiven"]].Status; s != "pinned" {
		t.Errorf("a second run: %s", s)
	}
	k.policy = refusingRunPolicy{}
	items.bump(edited.ID, "9", helperBody("changed"))
	refused, err := cat.RepinAll(ctx, false)
	if err != nil {
		t.Fatal(err)
	}
	if r := jobResults(refused, ws)[ids["edited"]]; r.Status != "refused" || r.Error == nil || !strings.Contains(*r.Error, "Install refused by policy") {
		t.Errorf("refused %+v", r)
	}
}

type refusingRunPolicy struct{ runFakePolicy }

func (refusingRunPolicy) RequireAllowed(context.Context, authn.Caller, string, string) error {
	return &govapi.InstallRefusedError{Reason: "no"}
}

func TestRefreshStubsReadsTheOriginalFromGitHub(t *testing.T) {
	ctx := context.Background()
	f := catalogSetup(t)
	b, k, c, items := f.b, f.k, f.c, f.items
	cat := CatalogSkills{K: k}
	ws := c.Workspace.ID()
	stub := f.insertPrePackage(t, "PDF", stubBody, nil)
	plain := f.insertPrePackage(t, "Plain", helperBody("plain"), nil)
	original := "---\nname: pdf\ndescription: The real PDF skill\n---\nbody"
	items.folder = catalogapi.GitHubFolder{Commit: "abc123", TreeSHA: "t", Files: map[string][]byte{domain.SkillManifest: []byte(original), "ref.md": []byte("r")}}

	dry, err := cat.RefreshStubs(ctx, true)
	if err != nil {
		t.Fatal(err)
	}
	got := jobResults(dry, ws)
	if r := got[stub]; r.Status != "would_refresh" || r.Error == nil || *r.Error != "anthropics/skills/document-skills/pdf" {
		t.Fatalf("dry run %+v", r)
	}
	if _, listed := got[plain]; listed || len(items.reads) != 0 {
		t.Fatalf("a skill that is no stub was reported, or GitHub read on a dry run: %+v %v", got, items.reads)
	}

	done, err := cat.RefreshStubs(ctx, false)
	if err != nil {
		t.Fatal(err)
	}
	r := jobResults(done, ws)[stub]
	if r.Status != "refreshed" || r.SourceURL == nil || *r.SourceURL != "https://github.com/anthropics/skills/tree/abc123/document-skills/pdf" ||
		r.Error == nil || *r.Error != "its SKILL.md names it 'pdf'; the name is kept; description taken from its SKILL.md" {
		t.Fatalf("refresh %+v", r)
	}
	if !slices.Contains(items.reads, "@anthropics/skills/document-skills/pdf") {
		t.Fatalf("GitHub reads %v", items.reads)
	}
	v, err := k.Get(ctx, c, uuid.MustParse(stub))
	if err != nil {
		t.Fatal(err)
	}
	if v.Name != "PDF" || v.SourceType != domain.SkillSourceGitHub || v.RegistryItemID != nil || *v.Description != "The real PDF skill" ||
		*v.SourceURL != *r.SourceURL || !domain.SkillIsWorkspacePackage(*v.S3Path) || string(b.objs[*v.S3Path+"ref.md"]) != "r" {
		t.Fatalf("refreshed skill %+v", v.Skill)
	}
	versions, err := k.Versions(ctx, c, uuid.MustParse(stub))
	if err != nil || len(versions) != 2 || versions[0].Reason != "migrate" || versions[1].Reason != "refresh" ||
		versions[1].CatalogVersion == nil || *versions[1].CatalogVersion != "abc123" {
		t.Fatalf("versions %+v %v", versions, err)
	}
	if again, _ := cat.RefreshStubs(ctx, false); len(jobResults(again, ws)) != 0 {
		t.Fatalf("a refreshed skill is still a stub: %+v", jobResults(again, ws))
	}
}
