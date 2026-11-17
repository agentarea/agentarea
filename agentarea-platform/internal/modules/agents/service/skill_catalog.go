package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	govapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// CatalogSkills implements SkillCatalog over the catalog's skill items.
type CatalogSkills struct{ K *Skills }

var _ SkillCatalog = CatalogSkills{}

// SkillCustomizedError is SkillCustomizedError: an update would discard the workspace's edit (409 skill_customized).
type SkillCustomizedError struct{ Msg string }

func (e *SkillCustomizedError) Error() string { return e.Msg }

// SkillNotFromCatalogError is SkillNotFromCatalogError: no catalog item to update from (409 skill_not_from_catalog).
type SkillNotFromCatalogError struct{ Msg string }

func (e *SkillNotFromCatalogError) Error() string { return e.Msg }

func samePtr(a, b *string) bool {
	return (a == nil && b == nil) || (a != nil && b != nil && *a == *b)
}

func itemSpec(item catalogapi.CatalogItem) (map[string]any, error) {
	spec := map[string]any{}
	if len(item.Spec) > 0 && string(item.Spec) != "null" {
		if err := json.Unmarshal(item.Spec, &spec); err != nil {
			return nil, fmt.Errorf("catalog skill %s: spec is not an object: %w", item.ID, err)
		}
	}
	return spec, nil
}

func (x CatalogSkills) ready() error {
	if x.K.items == nil {
		return x.K.unwiredCatalog()
	}
	if x.K.policy == nil {
		return &UnwiredError{Feature: "the catalog install policy"}
	}
	return nil
}

func (x CatalogSkills) load(ctx context.Context, ws scope.Workspace, id uuid.UUID) (domain.Skill, bool, error) {
	var sk domain.Skill
	var ok bool
	err := x.K.s.read(ctx, ws, func(sess db.Session) error {
		var err error
		sk, ok, err = x.K.get(ctx, sess, id)
		return err
	})
	return sk, ok, err
}

// Update is update_from_catalog; false when the workspace has no such skill.
func (x CatalogSkills) Update(ctx context.Context, c authn.Caller, skillID uuid.UUID, discardChanges bool) (SkillView, bool, error) {
	r, ok, err := x.update(ctx, c, skillID, discardChanges)
	if err != nil || !ok {
		return SkillView{}, ok, err
	}
	return *r.Skill, true, nil
}

func (x CatalogSkills) update(ctx context.Context, c authn.Caller, skillID uuid.UUID, discard bool) (SkillUpdateResult, bool, error) {
	if err := x.ready(); err != nil {
		return SkillUpdateResult{}, false, err
	}
	sk, ok, err := x.load(ctx, c.Workspace, skillID)
	if err != nil || !ok {
		return SkillUpdateResult{}, false, err
	}
	if sk.RegistryItemID == nil {
		return SkillUpdateResult{}, true, &SkillNotFromCatalogError{Msg: fmt.Sprintf("Skill %s was not installed from a catalog", sk.ID)}
	}
	item, found, err := x.K.items.SkillItem(ctx, c.Workspace, *sk.RegistryItemID)
	if err != nil {
		return SkillUpdateResult{}, true, err
	}
	if !found {
		return SkillUpdateResult{}, true, &SkillNotFromCatalogError{Msg: fmt.Sprintf("The catalog item skill %s was installed from is no longer listed", sk.ID)}
	}
	customized := domain.SkillIsCustomized(sk)
	if customized && !discard {
		return SkillUpdateResult{}, true, &SkillCustomizedError{Msg: fmt.Sprintf(
			"Skill %s was edited in this workspace; updating it would discard the edit. Pass discard_changes to update anyway.", sk.ID)}
	}
	status := "up_to_date"
	if customized || !samePtr(item.Version, item.InstalledVersion) {
		if sk, err = x.pin(ctx, c, sk, item, "update"); err != nil {
			return SkillUpdateResult{}, true, err
		}
		status = "updated"
	}
	if err := x.K.s.write(ctx, c.Workspace, func(sess db.Session) error {
		x.K.s.Audit(ctx, sess, c, "skill.update", "skill", sk.ID)
		return nil
	}); err != nil {
		return SkillUpdateResult{}, true, err
	}
	v := view(sk)
	return SkillUpdateResult{SkillID: sk.ID, Name: sk.Name, Status: status, Skill: &v}, true, nil
}

// UpdateAll is update_all_from_catalog: a customized skill is reported and
// left alone, a failed update reported with its reason while the rest go on.
func (x CatalogSkills) UpdateAll(ctx context.Context, c authn.Caller) ([]SkillUpdateResult, error) {
	if err := x.ready(); err != nil {
		return nil, err
	}
	var installed []domain.Skill
	if err := x.K.s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		installed, err = skills().FromCatalog(ctx, sess)
		return err
	}); err != nil {
		return nil, err
	}
	ids := map[string]bool{}
	for _, sk := range installed {
		ids[*sk.RegistryItemID] = true
	}
	versions, err := x.K.items.SkillVersions(ctx, c.Workspace, slices.Sorted(maps.Keys(ids)))
	if err != nil {
		return nil, err
	}
	results := []SkillUpdateResult{}
	for _, sk := range installed {
		v := versions[*sk.RegistryItemID]
		if v.Current == nil || *v.Current == "" || samePtr(v.Current, v.Installed) {
			continue
		}
		if domain.SkillIsCustomized(sk) {
			sv := view(sk)
			results = append(results, SkillUpdateResult{SkillID: sk.ID, Name: sk.Name, Status: "customized", Skill: &sv})
			continue
		}
		r, _, err := x.update(ctx, c, uuid.MustParse(sk.ID), false)
		if err != nil {
			x.K.warn(ctx, "Updating skill from its catalog item failed", "skill_id", sk.ID, "error", err.Error())
			msg := err.Error()
			r = SkillUpdateResult{SkillID: sk.ID, Name: sk.Name, Status: "failed", Error: &msg}
		}
		results = append(results, r)
	}
	return results, nil
}

// pin is _pin_to_catalog: sk points at its item's current package and the
// install's pin moves there; a pre-package copy it replaces is stored as a package first.
func (x CatalogSkills) pin(ctx context.Context, c authn.Caller, sk domain.Skill, item catalogapi.CatalogItem, reason string) (domain.Skill, error) {
	k := x.K
	if err := k.policy.RequireAllowed(ctx, c, item.RegistryID, item.RegistryTrust); err != nil {
		return domain.Skill{}, err
	}
	spec, err := itemSpec(item)
	if err != nil {
		return domain.Skill{}, err
	}
	pkg, err := k.catalogPackage(ctx, spec, item.RegistryWorkspaceID, "")
	if err != nil {
		return domain.Skill{}, err
	}
	pinned := pkg.treeSHA
	if pinned == nil {
		pinned = item.Version
	}
	sourceURL := pkg.sourceURL
	if sourceURL == nil {
		sourceURL = specString(spec, "source_url", false)
	}
	itemID, err := uuid.Parse(item.ID)
	if err != nil {
		return domain.Skill{}, fmt.Errorf("catalog skill id %q: %w", item.ID, err)
	}
	id := uuid.MustParse(sk.ID)
	var out domain.Skill
	err = k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		cur, ok, err := k.get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return ErrSkillNotFound
		}
		if domain.SkillIsOwnCopy(cur) {
			if _, err := k.moveOwnCopy(ctx, sess, c.UserID, &cur); err != nil {
				return err
			}
		}
		if err := k.items.MarkInstalled(ctx, sess, item.ID, sk.ID, pinned); err != nil {
			return err
		}
		moved, err := k.setPackage(ctx, sess, c.UserID, id, pkg.s3Path, reason, pinned, nil, false)
		if err != nil {
			return err
		}
		if !moved {
			return ErrSkillNotFound
		}
		if err := skills().SetSource(ctx, sess, id, store.SkillSource{SourceURL: sourceURL, SourceType: cur.SourceType,
			RegistryItemID: uuid.NullUUID{UUID: itemID, Valid: true}}, k.s.d.Now()); err != nil {
			return err
		}
		if out, ok, err = k.get(ctx, sess, id); err == nil && !ok {
			err = ErrSkillNotFound
		}
		return err
	})
	return out, err
}

// Pin is rollback's re-pin: the install policy, then the install marked at
// catalogVersion; nothing when the item is gone.
func (x CatalogSkills) Pin(ctx context.Context, s db.Session, c authn.Caller, skillID uuid.UUID, registryItemID string, catalogVersion *string) error {
	if err := x.ready(); err != nil {
		return err
	}
	item, ok, err := x.K.items.SkillItem(ctx, c.Workspace, registryItemID)
	if err != nil || !ok {
		return err
	}
	if err := x.K.policy.RequireAllowed(ctx, c, item.RegistryID, item.RegistryTrust); err != nil {
		return err
	}
	return x.K.items.MarkInstalled(ctx, s, item.ID, skillID.String(), catalogVersion)
}

// eachWorkspaceSkill runs one on every skill refs names under its own workspace
// as the platform; a failure is logged and reported as failure, and the rest go on.
func (x CatalogSkills) eachWorkspaceSkill(ctx context.Context, refs []store.SkillRef, failure, failMsg string,
	one func(ctx context.Context, c authn.Caller, id uuid.UUID) (SkillJobResult, bool, error)) []SkillJobResult {
	out := []SkillJobResult{}
	for _, r := range refs {
		ws, err := scope.NewWorkspace(r.WorkspaceID, "")
		var res SkillJobResult
		report := true
		if err == nil {
			res, report, err = one(ctx, authn.Caller{Principal: authn.Principal{UserID: SkillPlatformPrincipal}, Workspace: ws}, r.ID)
		}
		if err != nil {
			x.K.warn(ctx, failMsg, "skill_id", r.ID.String(), "workspace_id", r.WorkspaceID, "error", err.Error())
			msg := err.Error()
			res, report = SkillJobResult{SkillID: r.ID.String(), Name: res.Name, Status: failure, Error: &msg}, true
		}
		if report {
			res.WorkspaceID = r.WorkspaceID
			out = append(out, res)
		}
	}
	return out
}

// RepinAll is repin_all_catalog_installs.
func (x CatalogSkills) RepinAll(ctx context.Context, dryRun bool) ([]SkillJobResult, error) {
	if err := x.ready(); err != nil {
		return nil, err
	}
	if _, err := x.K.store(); err != nil {
		return nil, err
	}
	refs, err := x.K.globalRefs(ctx, func(q db.Querier) ([]store.SkillRef, error) {
		return skills().CatalogInstalls(ctx, q, SkillPlatformWorkspace)
	})
	if err != nil {
		return nil, err
	}
	return x.eachWorkspaceSkill(ctx, refs, "failed", "Failed to repin skill",
		func(ctx context.Context, c authn.Caller, id uuid.UUID) (SkillJobResult, bool, error) {
			r, err := x.repin(ctx, c, id, dryRun)
			return r, true, err
		}), nil
}

// repin is repin_from_catalog.
func (x CatalogSkills) repin(ctx context.Context, c authn.Caller, id uuid.UUID, dryRun bool) (SkillJobResult, error) {
	sk, ok, err := x.load(ctx, c.Workspace, id)
	if err != nil {
		return SkillJobResult{}, err
	}
	if !ok {
		return SkillJobResult{}, ErrSkillNotFound
	}
	result := func(status, detail string) (SkillJobResult, error) {
		r := SkillJobResult{SkillID: sk.ID, Name: sk.Name, Status: status}
		if detail != "" {
			r.Error = &detail
		}
		return r, nil
	}
	if sk.RegistryItemID == nil {
		return result("not_installed", "")
	}
	item, found, err := x.K.items.SkillItem(ctx, c.Workspace, *sk.RegistryItemID)
	if err != nil {
		return SkillJobResult{}, err
	}
	var spec map[string]any
	if found {
		if spec, err = itemSpec(item); err != nil {
			return SkillJobResult{}, err
		}
	}
	switch {
	case sk.S3Path != nil && domain.SkillIsCatalogPackage(*sk.S3Path):
		if !found || samePtr(item.Version, item.InstalledVersion) {
			return result("pinned", "")
		}
		held, known, err := x.holdsReplacedBody(ctx, sk, item, spec)
		if err != nil {
			return SkillJobResult{}, err
		}
		if !known || !held {
			return result("pinned", "")
		}
	case !found:
		return result("gone", "its catalog item is no longer listed")
	default:
		given, known, err := x.holdsWhatItGave(ctx, sk, item, spec)
		if err != nil {
			return SkillJobResult{}, err
		}
		if !known {
			return result("unverified", "its catalog item no longer carries the body it gave")
		}
		if !given {
			return result("edited", "")
		}
	}
	if dryRun {
		return result("would_repin", "")
	}
	pinned, err := x.pin(ctx, c, sk, item, "repin")
	var refused *govapi.InstallRefusedError
	var gh *domain.SkillGitHubError
	switch {
	case errors.As(err, &refused):
		return result("refused", err.Error())
	case errors.As(err, &gh) && gh.Kind == domain.SkillGitHubNotFound:
		return result("gone", err.Error())
	case err != nil:
		return SkillJobResult{}, err
	}
	sk = pinned
	return result("repinned", "")
}

// holdsWhatItGave is _holds_what_its_item_gave; known is false when the item
// no longer carries the body it gave to compare with.
func (x CatalogSkills) holdsWhatItGave(ctx context.Context, sk domain.Skill, item catalogapi.CatalogItem, spec map[string]any) (held, known bool, err error) {
	if s3, ok := spec["s3_path"].(string); ok && sk.S3Path != nil && *sk.S3Path != "" && *sk.S3Path == s3 {
		return true, true, nil
	}
	body, ok := spec["content"].(string)
	if !ok || body == "" {
		return x.holdsReplacedBody(ctx, sk, item, spec)
	}
	if sk.S3Path == nil {
		return sk.Content != nil && *sk.Content == body, true, nil
	}
	if !domain.SkillIsOwnCopy(sk) && !domain.SkillIsWorkspacePackage(*sk.S3Path) {
		return false, true, nil
	}
	files, err := x.K.readPackage(ctx, *sk.S3Path)
	if err != nil {
		return false, false, err
	}
	return len(files) == 1 && files[0].Path == domain.SkillManifest && bytes.Equal(files[0].Data, []byte(body)), true, nil
}

// holdsReplacedBody is _holds_the_body_its_item_replaced: whether sk holds
// exactly the inline body its item's GitHub pointer replaced, by the digest
// the sync kept, else by the stub an index wrote.
func (x CatalogSkills) holdsReplacedBody(ctx context.Context, sk domain.Skill, item catalogapi.CatalogItem, spec map[string]any) (held, known bool, err error) {
	source, ok := spec["source"].(map[string]any)
	if !ok || source["type"] != "github" {
		return false, false, nil
	}
	var files domain.SkillFiles
	if sk.S3Path != nil && *sk.S3Path != "" {
		if files, err = x.K.readPackage(ctx, *sk.S3Path); err != nil {
			return false, false, err
		}
	}
	if sk.Content != nil {
		files.Set(domain.SkillManifest, []byte(*sk.Content))
	}
	var body []byte
	if len(files) == 1 && files[0].Path == domain.SkillManifest {
		body = files[0].Data
	}
	if digest, ok := spec["replaced_body_sha256"].(string); ok {
		sum := sha256.Sum256(body)
		return body != nil && hex.EncodeToString(sum[:]) == digest, true, nil
	}
	if body == nil {
		return false, false, nil
	}
	stub, ok := bareStub(strings.ToValidUTF8(string(body), "�"), item.Name, item.Description)
	if ok && stub.repo == source["repo"] {
		return true, true, nil
	}
	return false, false, nil
}
