package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

type runFakePolicy struct{ deny map[string]string }

func (runFakePolicy) RequireAllowed(context.Context, authn.Caller, string, string) error { return nil }

func (p runFakePolicy) RunRefusal(_ context.Context, _ scope.Workspace, registry, _ string) (string, bool, error) {
	reason, ok := p.deny[registry]
	return reason, ok, nil
}

type runFakeCatalog struct {
	CatalogItems
	sources map[string]catalogapi.ItemSource
}

func (c runFakeCatalog) SkillProvenance(_ context.Context, _ scope.Workspace, ids []string) (map[string]catalogapi.ItemSource, error) {
	out := map[string]catalogapi.ItemSource{}
	for _, id := range ids {
		if s, ok := c.sources[id]; ok {
			out[id] = s
		}
	}
	return out, nil
}

func runSkillsSetup(t *testing.T, ports SkillPorts) (db.Database, *skillFakeBlob, RunSkills, authn.Caller) {
	t.Helper()
	d, _, _, b, k, c := skillSetup(t)
	ports.Blob = b
	return d, b, RunSkills{K: NewSkills(k.s, ports)}, c
}

func newRunSkill(t *testing.T, r RunSkills, c authn.Caller, body string) string {
	t.Helper()
	v, err := r.K.CreateFromContent(context.Background(), c, body, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	return v.ID
}

func runAgent(t *testing.T, d db.Database, c authn.Caller, skills ...string) string {
	t.Helper()
	id := uuid.New()
	ids := make([]uuid.UUID, len(skills))
	for i, s := range skills {
		ids[i] = uuid.MustParse(s)
	}
	err := d.Write(context.Background(), c.Workspace, func(ctx context.Context, s db.Session) error {
		if _, err := s.Q().Exec(ctx, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'a', 'active', $2, 'u', $3)`,
			id, c.Workspace.ID(), "a-"+id.String()[:8]); err != nil {
			return err
		}
		return store.Agents{}.SetSkills(ctx, s, id, ids, time.Now())
	})
	if err != nil {
		t.Fatal(err)
	}
	return id.String()
}

func TestRunSkillsOfferTheAgentsAndTheSelectedWithholdingRefused(t *testing.T) {
	ctx := context.Background()
	d, _, r, c := runSkillsSetup(t, SkillPorts{InstallPolicy: runFakePolicy{deny: map[string]string{"github": "community is denied"}}})
	pdf := newRunSkill(t, r, c, "---\nname: PDF\ndescription: Reads PDFs\n---\nbody")
	gh := newRunSkill(t, r, c, "---\nname: GH\n---\nfrom github")
	clientExec(t, d, c.Workspace, `UPDATE skills SET source_type = 'github' WHERE id = $1`, gh)
	extra := newRunSkill(t, r, c, "---\nname: Extra\n---\nextra")
	agent := runAgent(t, d, c, pdf, gh)

	offered, withheld, err := r.Offered(ctx, c.Workspace, agent, []string{extra, pdf, extra})
	if err != nil {
		t.Fatal(err)
	}
	if len(offered) != 2 || offered[0].ID != pdf || offered[0].Description != "Reads PDFs" || offered[0].Package == "" || offered[1].ID != extra {
		t.Fatalf("offered %+v", offered)
	}
	if len(withheld) != 1 || withheld[0].ID != gh || withheld[0].Reason != "community is denied" {
		t.Fatalf("withheld %+v", withheld)
	}

	if _, _, err := r.Offered(ctx, c.Workspace, agent, []string{gh}); err != nil {
		t.Fatalf("an agent's own refused skill is withheld, not refused: %v", err)
	}
	other := newRunSkill(t, r, c, "---\nname: Other GH\n---\nx")
	clientExec(t, d, c.Workspace, `UPDATE skills SET source_type = 'github' WHERE id = $1`, other)
	if _, _, err := r.Offered(ctx, c.Workspace, agent, []string{other}); !errors.Is(err, api.ErrSkillRefused) {
		t.Fatalf("a selected refused skill: %v", err)
	}
	if _, _, err := r.Offered(ctx, c.Workspace, agent, []string{uuid.NewString()}); !errors.Is(err, api.ErrSkillNotFound) {
		t.Fatalf("an unknown selected skill: %v", err)
	}
	if _, _, err := r.Offered(ctx, c.Workspace, agent, []string{"nope"}); !errors.Is(err, api.ErrSkillNotFound) {
		t.Fatalf("a malformed selected skill: %v", err)
	}
	twin := newRunSkill(t, r, c, "---\nname: PDF\n---\ntwin")
	if _, _, err := r.Offered(ctx, c.Workspace, agent, []string{twin}); !errors.Is(err, api.ErrSkillRefused) {
		t.Fatalf("a selected skill named like the agent's: %v", err)
	}
}

func TestRunSkillsAskTheCatalogForAnInstallsSource(t *testing.T) {
	ctx := context.Background()
	item, gone := uuid.NewString(), uuid.NewString()
	ports := SkillPorts{
		InstallPolicy: runFakePolicy{deny: map[string]string{"community-reg": "registry denied"}},
		Items:         runFakeCatalog{sources: map[string]catalogapi.ItemSource{item: {RegistryID: "community-reg", Trust: "community"}}},
	}
	d, _, r, c := runSkillsSetup(t, ports)
	installed := newRunSkill(t, r, c, "---\nname: Installed\n---\nx")
	orphan := newRunSkill(t, r, c, "---\nname: Orphan\n---\ny")
	clientExec(t, d, c.Workspace, `UPDATE skills SET registry_item_id = $2 WHERE id = $1`, installed, item)
	clientExec(t, d, c.Workspace, `UPDATE skills SET registry_item_id = $2 WHERE id = $1`, orphan, gone)
	agent := runAgent(t, d, c, installed, orphan)

	offered, withheld, err := r.Offered(ctx, c.Workspace, agent, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(offered) != 1 || offered[0].ID != orphan || len(withheld) != 1 || withheld[0].ID != installed {
		t.Fatalf("offered %+v withheld %+v", offered, withheld)
	}
	if err := r.Allow(ctx, c.Workspace, runsapi.Skill{ID: installed}); !errors.Is(err, api.ErrSkillRefused) {
		t.Fatalf("allow a refused install: %v", err)
	}

	_, _, bare, c2 := runSkillsSetup(t, SkillPorts{})
	unwired := newRunSkill(t, bare, c2, "---\nname: U\n---\nu")
	clientExec(t, d, c2.Workspace, `UPDATE skills SET registry_item_id = $2 WHERE id = $1`, unwired, item)
	if err := bare.Allow(ctx, c2.Workspace, runsapi.Skill{ID: unwired}); !errors.Is(err, api.ErrSkillRefused) {
		t.Fatalf("an install without the catalog is a final refusal: %v", err)
	}
}

func TestRunSkillsReadThePackageTheRunWasConfiguredWith(t *testing.T) {
	ctx := context.Background()
	d, b, r, c := runSkillsSetup(t, SkillPorts{})
	id := newRunSkill(t, r, c, "---\nname: Doc\n---\nv1")
	offered, _, err := r.Offered(ctx, c.Workspace, runAgent(t, d, c, id), nil)
	if err != nil {
		t.Fatal(err)
	}
	v1 := offered[0]
	if _, err := SkillToolset(r).SetContent(ctx, c, id, "---\nname: Doc\n---\nv2"); err != nil {
		t.Fatal(err)
	}
	if err := r.Allow(ctx, c.Workspace, v1); err != nil {
		t.Fatal(err)
	}
	body, err := r.ReadSkillMD(ctx, c.Workspace, v1)
	if err != nil || body != "---\nname: Doc\n---\nv1" {
		t.Fatalf("pinned body %q %v", body, err)
	}
	cur, err := r.ReadSkillMD(ctx, c.Workspace, runsapi.Skill{ID: id})
	if err != nil || cur != "---\nname: Doc\n---\nv2" {
		t.Fatalf("current body %q %v", cur, err)
	}
	b.objs[v1.Package+"scripts/run.sh"] = []byte("echo hi")
	files, err := r.PackageFiles(ctx, c.Workspace, v1)
	if err != nil || len(files) != 2 {
		t.Fatalf("files %+v %v", files, err)
	}

	foreign := v1
	foreign.Package = "skills/" + uuid.NewString() + "/packages/abc/"
	if _, err := r.ReadSkillMD(ctx, c.Workspace, foreign); !errors.Is(err, api.ErrSkillRefused) {
		t.Fatalf("another workspace's package: %v", err)
	}
	escape := v1
	escape.Package = "skills/catalog/../" + uuid.NewString() + "/"
	if _, err := r.PackageFiles(ctx, c.Workspace, escape); !errors.Is(err, api.ErrSkillRefused) {
		t.Fatalf("a path out of the areas: %v", err)
	}
	if _, err := r.ReadSkillMD(ctx, c.Workspace, runsapi.Skill{ID: uuid.NewString()}); !errors.Is(err, api.ErrSkillNotFound) {
		t.Fatalf("a deleted skill: %v", err)
	}
	missing := v1
	missing.Package = "skills/catalog/nothing-here/"
	if _, err := r.ReadSkillMD(ctx, c.Workspace, missing); !errors.Is(err, api.ErrSkillRefused) {
		t.Fatalf("a package without SKILL.md: %v", err)
	}
}

func TestRunSkillsReadAnUnmovedBodyAsItIs(t *testing.T) {
	ctx := context.Background()
	d, _, r, c := runSkillsSetup(t, SkillPorts{})
	id := newRunSkill(t, r, c, "---\nname: Old\n---\npackaged")
	clientExec(t, d, c.Workspace, `UPDATE skills SET content = 'in the row' WHERE id = $1`, id)
	body, err := r.ReadSkillMD(ctx, c.Workspace, runsapi.Skill{ID: id, Package: "skills/catalog/x/"})
	if err != nil || body != "in the row" {
		t.Fatalf("body %q %v", body, err)
	}
	files, err := r.PackageFiles(ctx, c.Workspace, runsapi.Skill{ID: id})
	if err != nil || len(files) != 1 || string(files[0].Data) != "in the row" {
		t.Fatalf("files %+v %v", files, err)
	}
}
