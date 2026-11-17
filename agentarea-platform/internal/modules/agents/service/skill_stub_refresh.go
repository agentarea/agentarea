package service

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	govapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// RefreshStubs is refresh_all_stub_installs: every skill outside the platform
// workspace whose SKILL.md is an old index's stub, re-read from the folder the
// stub names; a skill that is no stub is not reported.
func (x CatalogSkills) RefreshStubs(ctx context.Context, dryRun bool) ([]SkillJobResult, error) {
	if err := x.ready(); err != nil {
		return nil, err
	}
	if _, err := x.K.store(); err != nil {
		return nil, err
	}
	refs, err := x.K.globalRefs(ctx, func(q db.Querier) ([]store.SkillRef, error) {
		return skills().OutsidePlatform(ctx, q, SkillPlatformWorkspace)
	})
	if err != nil {
		return nil, err
	}
	return x.eachWorkspaceSkill(ctx, refs, "error", "Failed to refresh stub skill",
		func(ctx context.Context, c authn.Caller, id uuid.UUID) (SkillJobResult, bool, error) {
			sk, ok, err := x.load(ctx, c.Workspace, id)
			if err != nil || !ok {
				return SkillJobResult{}, false, err
			}
			text, err := x.storedSkillMD(ctx, sk)
			if err != nil {
				return SkillJobResult{Name: sk.Name}, true, err
			}
			stub, ok := parseStub(text)
			if !ok {
				return SkillJobResult{}, false, nil
			}
			r, err := x.refresh(ctx, c, sk, stub, dryRun)
			if err != nil {
				return SkillJobResult{Name: sk.Name}, true, err
			}
			return r, true, nil
		}), nil
}

// storedSkillMD is _stored_skill_md: the SKILL.md a skill holds, read where it lies.
func (x CatalogSkills) storedSkillMD(ctx context.Context, sk domain.Skill) (string, error) {
	if sk.Content != nil {
		return *sk.Content, nil
	}
	if sk.S3Path == nil || *sk.S3Path == "" {
		return "", &domain.SkillValueError{Msg: fmt.Sprintf("Skill %s has neither a package nor a body", sk.ID)}
	}
	infos, err := x.K.listFiles(ctx, *sk.S3Path)
	if err != nil {
		return "", err
	}
	paths := make([]string, len(infos))
	for i, f := range infos {
		paths[i] = f.Path
	}
	main, ok := domain.SkillMainFile(paths)
	if !ok {
		return "", &domain.SkillValueError{Msg: fmt.Sprintf("Skill %s package %s has no SKILL.md at its root", sk.ID, *sk.S3Path)}
	}
	data, err := x.K.fileContent(ctx, *sk.S3Path, main)
	if err != nil {
		return "", err
	}
	if !utf8.Valid(data) {
		return "", fmt.Errorf("skill %s: %s is not UTF-8", sk.ID, main)
	}
	return string(data), nil
}

// stubSource is _github_source: (repo, folder) from the stub, else from its catalog item's GitHub source.
func (x CatalogSkills) stubSource(ctx context.Context, c authn.Caller, sk domain.Skill, stub skillStub) (string, string, error) {
	if stubRepoName.MatchString(stub.repo) {
		return stub.repo, stub.folder(), nil
	}
	if sk.RegistryItemID != nil {
		item, found, err := x.K.items.SkillItem(ctx, c.Workspace, *sk.RegistryItemID)
		if err != nil {
			return "", "", err
		}
		if found {
			spec, err := itemSpec(item)
			if err != nil {
				return "", "", err
			}
			source, _ := spec["source"].(map[string]any)
			if repo, ok := source["repo"].(string); ok && source["type"] == "github" && repo != "" {
				p, _ := source["path"].(string)
				return repo, strings.Trim(p, "/"), nil
			}
		}
	}
	return "", "", &domain.SkillValueError{Msg: "The stub names no GitHub repository: " + domain.SkillRepr(stub.repo)}
}

// refresh is refresh_stub: sk points at the folder its stub names, read at the
// default branch's head as a GitHub import; the stub it held is recorded first.
func (x CatalogSkills) refresh(ctx context.Context, c authn.Caller, sk domain.Skill, stub skillStub, dryRun bool) (SkillJobResult, error) {
	k := x.K
	result := func(status, detail string, sourceURL *string) (SkillJobResult, error) {
		r := SkillJobResult{SkillID: sk.ID, Name: sk.Name, Status: status, SourceURL: sourceURL}
		if detail != "" {
			r.Error = &detail
		}
		return r, nil
	}
	repo, folder, err := x.stubSource(ctx, c, sk, stub)
	if err != nil {
		return SkillJobResult{}, err
	}
	where := repo
	if folder != "" {
		where += "/" + folder
	}
	var refused *govapi.InstallRefusedError
	if err := k.policy.RequireAllowed(ctx, c, SkillGitHubRegistryID, SkillGitHubTrust); errors.As(err, &refused) {
		return result("refused", err.Error(), nil)
	} else if err != nil {
		return SkillJobResult{}, err
	}
	if dryRun {
		return result("would_refresh", where, nil)
	}
	fetched, err := k.items.Folder(ctx, "", repo, folder, nil, nil)
	var fe *catalogapi.FolderError
	if errors.As(err, &fe) && fe.NotFound {
		return result("not_found", err.Error(), nil)
	}
	if err != nil {
		return SkillJobResult{}, err
	}
	files := domain.SkillFiles{}
	for _, p := range slices.Sorted(maps.Keys(fetched.Files)) {
		files.Set(p, fetched.Files[p])
	}
	main, ok := domain.SkillMainFile(files.Paths())
	if !ok {
		return SkillJobResult{}, &domain.SkillValueError{Msg: fmt.Sprintf("%s at %s: %s", where, fetched.Commit, domain.SkillMissingManifest)}
	}
	data, _ := files.Get(main)
	if !utf8.Valid(data) {
		return SkillJobResult{}, fmt.Errorf("%s at %s: %s is not UTF-8", where, fetched.Commit, main)
	}
	meta, err := SkillParse(string(data))
	if err != nil {
		return SkillJobResult{}, err
	}
	s3, err := k.storeWorkspacePackage(ctx, files, sk.WorkspaceID)
	if err != nil {
		return SkillJobResult{}, err
	}
	sourceURL := "https://github.com/" + repo + "/tree/" + fetched.Commit
	if folder != "" {
		sourceURL += "/" + folder
	}
	var notes []string
	if meta.Name != sk.Name {
		notes = append(notes, "its SKILL.md names it "+domain.SkillRepr(meta.Name)+"; the name is kept")
	}
	var description *string
	if meta.Description != nil && *meta.Description != "" && !samePtr(meta.Description, sk.Description) {
		description = meta.Description
		notes = append(notes, "description taken from its SKILL.md")
	}
	id := uuid.MustParse(sk.ID)
	err = k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		cur, ok, err := k.get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return fmt.Errorf("skill %s vanished while it was refreshed", sk.ID)
		}
		held, err := k.resolve(ctx, sess, c.UserID, &cur, true)
		if err != nil {
			return err
		}
		moved, err := k.setPackage(ctx, sess, c.UserID, id, s3, "refresh", &fetched.Commit, &held, true)
		if err != nil {
			return err
		}
		if !moved {
			return fmt.Errorf("skill %s vanished while it was refreshed", sk.ID)
		}
		return skills().SetSource(ctx, sess, id, store.SkillSource{SourceURL: &sourceURL, SourceType: domain.SkillSourceGitHub,
			Description: description}, k.s.d.Now())
	})
	if err != nil {
		return SkillJobResult{}, err
	}
	return result("refreshed", strings.Join(notes, "; "), &sourceURL)
}
