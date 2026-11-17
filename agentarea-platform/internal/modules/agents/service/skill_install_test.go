package service

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

type installFakeItems struct {
	CatalogItems
	items  map[string]catalogapi.CatalogItem
	marked []string
	inTx   bool
}

func (f *installFakeItems) SkillItem(_ context.Context, _ scope.Workspace, id string) (catalogapi.CatalogItem, bool, error) {
	it, ok := f.items[id]
	return it, ok, nil
}

func (f *installFakeItems) MarkInstalled(_ context.Context, s db.Session, itemID, entityID string, version *string) error {
	f.inTx = s.Workspace().ID() != ""
	f.marked = append(f.marked, itemID+"="+entityID+"@"+*version)
	return nil
}

type installRefusingPolicy struct{ runFakePolicy }

func (installRefusingPolicy) RequireAllowed(context.Context, authn.Caller, string, string) error {
	return errors.New("refused")
}

func catalogSkillItem(spec map[string]any) catalogapi.CatalogItem {
	raw, _ := json.Marshal(spec)
	v := "1.2.0"
	return catalogapi.CatalogItem{ID: uuid.NewString(), Name: "Catalog helper", Version: &v, Spec: raw,
		RegistryID: "reg-1", RegistryTrust: "verified"}
}

func TestInstallForksACatalogSkillOnceAndPinsIt(t *testing.T) {
	ctx := context.Background()
	d, _, _, b, k, c := skillSetup(t)
	item := catalogSkillItem(map[string]any{"content": "---\nname: Catalog helper\ndescription: Helps\n---\nbody", "description": "From spec"})
	items := &installFakeItems{items: map[string]catalogapi.CatalogItem{item.ID: item}}
	k.items, k.policy = items, runFakePolicy{}

	v, err := k.Install(ctx, c, uuid.MustParse(item.ID))
	if err != nil {
		t.Fatal(err)
	}
	if v.RegistryItemID == nil || *v.RegistryItemID != item.ID || v.S3Path == nil || !strings.HasPrefix(*v.S3Path, "skills/catalog/") {
		t.Fatalf("fork: %+v", v.Skill)
	}
	if v.Description == nil || *v.Description != "From spec" || v.SourceType != domain.SkillSourceContent || v.NetworkScope != "private" {
		t.Fatalf("fork fields: %+v", v.Skill)
	}
	if _, ok := b.objs[*v.S3Path+domain.SkillManifest]; !ok {
		t.Fatalf("package not stored at %s", *v.S3Path)
	}
	if len(items.marked) != 1 || items.marked[0] != item.ID+"="+v.ID+"@1.2.0" || !items.inTx {
		t.Fatalf("install mark: %v (in tx %v)", items.marked, items.inTx)
	}
	versions, err := k.Versions(ctx, c, uuid.MustParse(v.ID))
	if err != nil {
		t.Fatal(err)
	}
	if len(versions) != 1 || versions[0].Reason != "install" || versions[0].CatalogVersion == nil || *versions[0].CatalogVersion != "1.2.0" {
		t.Fatalf("versions: %+v", versions)
	}

	again, err := k.Install(ctx, c, uuid.MustParse(item.ID))
	if err != nil || again.ID != v.ID || len(items.marked) != 1 {
		t.Fatalf("second install made another copy: %v %s vs %s", err, again.ID, v.ID)
	}
	_ = d
}

func TestInstallAsksThePolicyBeforeWriting(t *testing.T) {
	ctx := context.Background()
	_, _, _, b, k, c := skillSetup(t)
	item := catalogSkillItem(map[string]any{"content": "---\nname: x\n---\ny"})
	items := &installFakeItems{items: map[string]catalogapi.CatalogItem{item.ID: item}}
	k.items, k.policy = items, installRefusingPolicy{}
	if _, err := k.Install(ctx, c, uuid.MustParse(item.ID)); err == nil || err.Error() != "refused" {
		t.Fatalf("want the refusal, got %v", err)
	}
	if len(items.marked) != 0 || len(b.objs) != 0 {
		t.Fatalf("a refused install wrote: %v %d objects", items.marked, len(b.objs))
	}
}

func TestInstallRefusesAnItemWithoutAPackage(t *testing.T) {
	ctx := context.Background()
	_, _, _, _, k, c := skillSetup(t)
	ws := c.Workspace.ID()
	foreign := catalogSkillItem(map[string]any{"package": map[string]any{"s3_path": "skills/other/catalog/abc/"}})
	foreign.RegistryWorkspaceID = &ws
	empty := catalogSkillItem(map[string]any{})
	k.items = &installFakeItems{items: map[string]catalogapi.CatalogItem{foreign.ID: foreign, empty.ID: empty}}
	k.policy = runFakePolicy{}
	for _, it := range []catalogapi.CatalogItem{foreign, empty} {
		var ve *domain.SkillValueError
		if _, err := k.Install(ctx, c, uuid.MustParse(it.ID)); !errors.As(err, &ve) {
			t.Fatalf("%s: want a value error, got %v", it.Spec, err)
		}
	}
	if _, err := k.Install(ctx, c, uuid.New()); !errors.Is(err, ErrSkillNotFound) {
		t.Fatalf("unknown item: %v", err)
	}
}
