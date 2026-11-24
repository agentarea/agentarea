package store

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

func TestSkillRowsVersionsAndMembers(t *testing.T) {
	ctx := context.Background()
	pool, s, other := session(t)
	var k Skills
	now := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)
	desc, url := "Reads PDFs", "https://github.com/a/b"
	a, b := uuid.New(), uuid.New()
	if err := k.Insert(ctx, s, SkillNew{ID: a, Name: "PDF", Slug: "pdf", Description: &desc, SourceType: "github", SourceURL: &url, CreatedBy: "u1"}, now); err != nil {
		t.Fatal(err)
	}
	if err := k.Insert(ctx, s, SkillNew{ID: b, Name: "Other", Slug: "other", SourceType: "content", CreatedBy: "u1"}, now.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	if taken, _ := k.SlugTaken(ctx, s, "pdf"); !taken {
		t.Error("slug not taken")
	}
	if taken, _ := k.SlugTaken(ctx, other, "pdf"); taken {
		t.Error("slug is per workspace")
	}
	sk, ok, err := k.Get(ctx, s, a)
	if err != nil || !ok || sk.NetworkScope != "private" || sk.S3Path != nil || sk.Content != nil || *sk.SourceURL != url {
		t.Fatalf("%+v %v %v", sk, ok, err)
	}
	if _, ok, _ := k.Get(ctx, other, a); ok {
		t.Fatal("another workspace reads the skill")
	}

	search, src := "  pdf ", "github"
	rows, total, err := k.Page(ctx, s, SkillFilter{IDs: []uuid.UUID{a, b}, Search: &search, Limit: 10})
	if err != nil || total != 1 || rows[0].ID != a.String() {
		t.Fatalf("search %v %d %v", rows, total, err)
	}
	if _, total, _ := k.Page(ctx, s, SkillFilter{IDs: []uuid.UUID{a, b}, SourceType: &src, Limit: 10}); total != 1 {
		t.Errorf("source_type %d", total)
	}
	rows, total, _ = k.Page(ctx, s, SkillFilter{IDs: []uuid.UUID{a, b}, Limit: 1})
	if total != 2 || len(rows) != 1 || rows[0].ID != b.String() {
		t.Errorf("newest first %v %d", rows, total)
	}
	fromReg := true
	if _, total, _ := k.Page(ctx, s, SkillFilter{IDs: []uuid.UUID{a, b}, FromRegistry: &fromReg, Limit: 10}); total != 0 {
		t.Errorf("from_registry %d", total)
	}

	p1, p2 := "skills/w/packages/d1/", "skills/w/packages/d2/"
	if err := k.SetPackage(ctx, s, a, p1, now); err != nil {
		t.Fatal(err)
	}
	if swapped, err := k.SwapPackage(ctx, s, a, p2, &p2, now); err != nil || swapped {
		t.Errorf("stale expect swapped: %v %v", swapped, err)
	}
	if swapped, err := k.SwapPackage(ctx, s, a, p2, &p1, now); err != nil || !swapped {
		t.Errorf("swap %v %v", swapped, err)
	}
	for i, p := range []string{p1, p2} {
		d := "d" + string(rune('1'+i))
		if err := k.AddVersion(ctx, s, domain.SkillVersion{ID: uuid.NewString(), SkillID: a.String(), S3Path: p, Digest: &d, Reason: "edit", CreatedBy: "u1"}, now.Add(time.Duration(i)*time.Second)); err != nil {
			t.Fatal(err)
		}
	}
	vs, err := k.Versions(ctx, s, a)
	if err != nil || len(vs) != 2 || vs[0].S3Path != p1 {
		t.Fatalf("%+v %v", vs, err)
	}
	if last, ok, _ := k.LatestVersion(ctx, s, a); !ok || last.S3Path != p2 {
		t.Errorf("latest %+v", last)
	}
	if _, ok, _ := k.Version(ctx, other, a, uuid.MustParse(vs[0].ID)); ok {
		t.Error("another workspace reads the version")
	}

	if err := k.PutMember(ctx, s, domain.SkillMember{ParentSkillID: a.String(), ChildSkillID: b.String(), Order: 3, IsRequired: true, Dependencies: []string{"x"}}); err != nil {
		t.Fatal(err)
	}
	if err := k.PutMember(ctx, s, domain.SkillMember{ParentSkillID: a.String(), ChildSkillID: b.String(), Order: 4, Dependencies: []string{}}); err != nil {
		t.Fatal(err)
	}
	ms, err := k.Members(ctx, s, a)
	if err != nil || len(ms) != 1 || ms[0].Order != 4 || ms[0].IsRequired || len(ms[0].Dependencies) != 0 {
		t.Fatalf("%+v %v", ms, err)
	}
	if ok, _ := k.RemoveMember(ctx, s, a, b); !ok {
		t.Error("remove")
	}
	if ok, _ := k.RemoveMember(ctx, s, a, b); ok {
		t.Error("removed twice")
	}

	refs, err := k.AtOwnCopies(ctx, pool)
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range refs {
		if r.ID == a {
			t.Error("a package is not an own copy")
		}
	}
	if ok, _ := k.Delete(ctx, other, a); ok {
		t.Error("another workspace deletes the skill")
	}
	if ok, _ := k.Delete(ctx, s, a); !ok {
		t.Error("delete")
	}
}
