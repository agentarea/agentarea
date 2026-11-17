package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

// installItem is install_catalog_skill past the tenant lookup: the
// workspace's earlier fork of the item, else a new one; false when no item has id.
func (k *Skills) installItem(ctx context.Context, c authn.Caller, id uuid.UUID) (domain.Skill, bool, error) {
	if k.items == nil {
		return domain.Skill{}, false, k.unwiredCatalog()
	}
	item, ok, err := k.items.SkillItem(ctx, c.Workspace, id.String())
	if err != nil || !ok {
		return domain.Skill{}, false, err
	}
	var forked domain.Skill
	var has bool
	if err := k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		forked, has, err = skills().ByRegistryItem(ctx, sess, id)
		return err
	}); err != nil {
		return domain.Skill{}, false, err
	}
	if has {
		return forked, true, nil
	}
	sk, err := k.fork(ctx, c, item)
	return sk, err == nil, err
}

// catalogPackage is CatalogPackage: a stored package and where it came from.
type catalogPackage struct {
	s3Path    string
	sourceURL *string
	treeSHA   *string
}

// fork is _fork_catalog_skill: the install policy, the item's package, then
// the workspace's row pinned to it, in one transaction with the install mark.
func (k *Skills) fork(ctx context.Context, c authn.Caller, item catalogapi.CatalogItem) (domain.Skill, error) {
	if k.policy == nil {
		return domain.Skill{}, &UnwiredError{Feature: "the catalog install policy"}
	}
	if err := k.policy.RequireAllowed(ctx, c, item.RegistryID, item.RegistryTrust); err != nil {
		return domain.Skill{}, err
	}
	spec := map[string]any{}
	if len(item.Spec) > 0 && string(item.Spec) != "null" {
		if err := json.Unmarshal(item.Spec, &spec); err != nil {
			return domain.Skill{}, fmt.Errorf("catalog skill %s: spec is not an object: %w", item.ID, err)
		}
	}
	pkg, err := k.catalogPackage(ctx, spec, item.RegistryWorkspaceID, "")
	if err != nil {
		return domain.Skill{}, err
	}
	pinned := pkg.treeSHA
	if pinned == nil {
		pinned = item.Version
	}
	itemID, err := uuid.Parse(item.ID)
	if err != nil {
		return domain.Skill{}, fmt.Errorf("catalog skill id %q: %w", item.ID, err)
	}
	description := item.Description
	if description == nil {
		description = specString(spec, "description", false)
	}
	sourceURL := pkg.sourceURL
	if sourceURL == nil {
		sourceURL = specString(spec, "source_url", true)
	}
	id := uuid.New()
	var out domain.Skill
	err = k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		slug, err := k.uniqueSlug(ctx, sess, item.Name)
		if err != nil {
			return err
		}
		now := k.s.d.Now()
		if err := skills().InsertFork(ctx, sess, store.SkillFork{
			SkillNew: store.SkillNew{ID: id, Name: item.Name, Slug: slug, Description: description,
				SourceType: specOr(spec, "source_type", domain.SkillSourceContent), SourceURL: sourceURL, CreatedBy: c.UserID},
			S3Path: pkg.s3Path, NetworkScope: specOr(spec, "network_scope", "private"), RegistryItemID: itemID,
		}, now); err != nil {
			return err
		}
		if err := k.items.MarkInstalled(ctx, sess, item.ID, id.String(), pinned); err != nil {
			return err
		}
		if err := skills().AddVersion(ctx, sess, domain.SkillVersion{
			ID: uuid.NewString(), SkillID: id.String(), S3Path: pkg.s3Path, Digest: domain.SkillPackageDigestOf(&pkg.s3Path),
			Reason: "install", CatalogVersion: pinned, CreatedBy: c.UserID,
		}, now); err != nil {
			return err
		}
		var ok bool
		if out, ok, err = k.get(ctx, sess, id); err != nil || !ok {
			if err == nil {
				err = errors.New("skill vanished after its install")
			}
			return err
		}
		return nil
	})
	if err != nil {
		return domain.Skill{}, err
	}
	return out, nil
}

// specString is spec.get(key), "" read as absent when falsy is set.
func specString(spec map[string]any, key string, falsy bool) *string {
	s, ok := spec[key].(string)
	if !ok || (falsy && s == "") {
		return nil
	}
	return &s
}

// specOr is spec.get(key) or fallback.
func specOr(spec map[string]any, key, fallback string) string {
	if s := specString(spec, key, true); s != nil {
		return *s
	}
	return fallback
}

// catalogPackage is store_catalog_item: a mirrored package as it is, a GitHub
// pointer fetched at its pin (as token, when set), an inline body as SKILL.md, a legacy package copied.
func (k *Skills) catalogPackage(ctx context.Context, spec map[string]any, registryWS *string, token string) (catalogPackage, error) {
	area := domain.SkillCatalogArea(registryWS)
	source, _ := spec["source"].(map[string]any)
	if mirrored, ok := spec["package"].(map[string]any); ok {
		s3, _ := mirrored["s3_path"].(string)
		if !strings.HasPrefix(s3, area+"/") || !domain.SkillIsCatalogPackage(s3) ||
			slices.Contains(strings.Split(s3, "/"), "..") || strings.Contains(s3, `\`) {
			return catalogPackage{}, &domain.SkillValueError{Msg: fmt.Sprintf(
				"Catalog skill's mirrored package %s is outside its registry's store", domain.SkillRepr(s3))}
		}
		p := catalogPackage{s3Path: s3, sourceURL: specString(mirrored, "source_url", true), treeSHA: specString(mirrored, "tree_sha", true)}
		if p.sourceURL == nil {
			p.sourceURL = specString(spec, "source_url", true)
		}
		if p.treeSHA == nil && source != nil {
			p.treeSHA = specString(source, "tree_sha", true)
		}
		return p, nil
	}
	if source != nil && source["type"] == "github" {
		return k.githubPackage(ctx, source, area, token)
	}
	if content := specString(spec, "content", true); content != nil {
		s3, err := k.storeChecked(ctx, area, domain.SkillFiles{{Path: domain.SkillManifest, Data: []byte(*content)}})
		return catalogPackage{s3Path: s3, sourceURL: specString(spec, "source_url", false)}, err
	}
	if raw := specString(spec, "s3_path", true); raw != nil {
		legacy := domain.SkillLegacyCatalogPath(*raw, registryWS, SkillPlatformWorkspace)
		if legacy == "" {
			return catalogPackage{}, &domain.SkillValueError{Msg: fmt.Sprintf(
				"Catalog skill's package %s is outside its registry's store", domain.SkillRepr(*raw))}
		}
		files, err := k.readPackage(ctx, legacy)
		if err != nil {
			return catalogPackage{}, err
		}
		s3, err := k.storeChecked(ctx, area, files)
		return catalogPackage{s3Path: s3, sourceURL: specString(spec, "source_url", false)}, err
	}
	return catalogPackage{}, &domain.SkillValueError{Msg: "Catalog skill carries neither a source, a body nor a package"}
}

// githubPackage is _store_github_source without its process caches.
func (k *Skills) githubPackage(ctx context.Context, source map[string]any, area, token string) (catalogPackage, error) {
	repo, ok := source["repo"].(string)
	if !ok || repo == "" {
		return catalogPackage{}, &domain.SkillValueError{Msg: "Catalog skill's GitHub source names no repo"}
	}
	path := ""
	if p, ok := source["path"].(string); ok {
		path = strings.Trim(p, "/")
	}
	folder, err := k.items.Folder(ctx, token, repo, path, specString(source, "ref", false), specString(source, "tree_sha", true))
	var fe *catalogapi.FolderError
	if errors.As(err, &fe) {
		kind := domain.SkillGitHubOther
		switch {
		case fe.RateLimited:
			kind = domain.SkillGitHubRateLimited
		case fe.NotFound:
			kind = domain.SkillGitHubNotFound
		}
		return catalogPackage{}, &domain.SkillGitHubError{Kind: kind, Msg: fe.Msg}
	}
	if err != nil {
		return catalogPackage{}, err
	}
	files := domain.SkillFiles{}
	for _, p := range slices.Sorted(maps.Keys(folder.Files)) {
		files.Set(p, folder.Files[p])
	}
	s3, err := k.storeChecked(ctx, area, files)
	if err != nil {
		return catalogPackage{}, err
	}
	url := "https://github.com/" + repo + "/tree/" + folder.Commit
	if path != "" {
		url += "/" + path
	}
	return catalogPackage{s3Path: s3, sourceURL: &url, treeSHA: &folder.TreeSHA}, nil
}

// storeChecked is _store_checked: a package whose SKILL.md parses, stored in area.
func (k *Skills) storeChecked(ctx context.Context, area string, files domain.SkillFiles) (string, error) {
	main, ok := domain.SkillMainFile(files.Paths())
	if !ok {
		return "", &domain.SkillValueError{Msg: domain.SkillMissingManifest}
	}
	data, _ := files.Get(main)
	if _, err := SkillParse(string(data)); err != nil {
		return "", err
	}
	if _, err := k.store(); err != nil {
		return "", err
	}
	return k.storeByDigest(ctx, area, files)
}
