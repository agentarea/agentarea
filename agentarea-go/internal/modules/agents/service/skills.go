package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

// Skills serves the skill routes (skills, packages, GitHub import, catalog update).
type Skills struct {
	s       *Service
	blob    blob.Store
	github  http.RoundTripper
	catalog SkillCatalog
	items   CatalogItems
	policy  SkillInstallPolicy
}

// NewSkills builds the service over the agents service.
func NewSkills(s *Service, p SkillPorts) *Skills {
	return &Skills{s: s, blob: p.Blob, github: p.GitHub, catalog: p.Catalog, items: p.Items, policy: p.InstallPolicy}
}

// SkillView is a skill as SkillResponse renders it: the row and what the
// catalog says about it (nothing until the catalog module serves skills).
type SkillView struct {
	domain.Skill
	IsCatalog       bool
	UpdateAvailable bool
	RegistryName    *string
	RegistryScope   *string
	RegistryTrust   *string
	RemovedUpstream bool
}

// SkillVersionView is a version and whether the skill runs it now.
type SkillVersionView struct {
	domain.SkillVersion
	Current bool
}

// SkillFileView is SkillFileInfo.
type SkillFileView struct {
	Path string
	Size int64
	URL  *string
}

// SkillListQuery is list_skills' parameters.
type SkillListQuery struct {
	Offset, Limit  int
	Search         *string
	SourceType     *string
	NetworkScope   *string
	FromRegistry   *bool
	IncludeCatalog bool
}

// ErrSkillVersionNotFound is SkillVersionNotFoundError, rendered 404 "Skill version not found".
var ErrSkillVersionNotFound = errors.New("skill version not found")

// SkillNotFoundError is NotFoundError("Skill not found"): the problem a bundle route answers.
type SkillNotFoundError struct{}

func (*SkillNotFoundError) Error() string { return "Skill not found" }

// SkillMemberNotFoundError is remove_skill_member's 404 "Member association not found".
type SkillMemberNotFoundError struct{}

func (*SkillMemberNotFoundError) Error() string { return "Member association not found" }

// SkillFilesError is a ValueError the file routes answer 404 with.
type SkillFilesError struct{ Msg string }

func (e *SkillFilesError) Error() string { return e.Msg }

// The source a GitHub import is checked as (constants.py GITHUB_IMPORT_*).
const (
	SkillGitHubRegistryID = "github"
	SkillGitHubTrust      = "community"
)

func view(sk domain.Skill) SkillView { return SkillView{Skill: sk} }

func (k *Skills) unwiredCatalog() error { return &UnwiredError{Feature: "the skill catalog"} }

func (k *Skills) get(ctx context.Context, sess db.Session, id uuid.UUID) (domain.Skill, bool, error) {
	return skills().Get(ctx, sess, id)
}

// List is list_skills: the tenant rows the graph says the caller may read.
func (k *Skills) List(ctx context.Context, c authn.Caller, q SkillListQuery) ([]SkillView, int, error) {
	readable, err := authz.ReadableResourceIDs(ctx, k.s.d.Graph, c.GraphSubject())
	if err != nil {
		return nil, 0, err
	}
	ids := make([]uuid.UUID, 0, len(readable))
	for id := range readable {
		if u, err := uuid.Parse(id); err == nil {
			ids = append(ids, u)
		}
	}
	var rows []domain.Skill
	var total int
	err = k.s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		rows, total, err = skills().Page(ctx, sess, store.SkillFilter{IDs: ids, Search: q.Search, SourceType: q.SourceType,
			NetworkScope: q.NetworkScope, FromRegistry: q.FromRegistry, Offset: q.Offset, Limit: q.Limit})
		return err
	})
	if err != nil {
		return nil, 0, err
	}
	out := make([]SkillView, len(rows))
	for i, r := range rows {
		out[i] = view(r)
	}
	return out, total, nil
}

// Get is get_skill: the tenant row, then the PDP read check.
func (k *Skills) Get(ctx context.Context, c authn.Caller, id uuid.UUID) (SkillView, error) {
	var sk domain.Skill
	var ok bool
	if err := k.s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		sk, ok, err = k.get(ctx, sess, id)
		return err
	}); err != nil {
		return SkillView{}, err
	}
	if !ok {
		return SkillView{}, ErrSkillNotFound
	}
	if err := k.s.Require(ctx, c, "read", id); err != nil {
		return SkillView{}, err
	}
	return view(sk), nil
}

func (k *Skills) uniqueSlug(ctx context.Context, sess db.Session, name string) (string, error) {
	base := domain.Slug(name)
	for i := 1; i <= domain.MaxSlugSuffix; i++ {
		cand := base
		if i > 1 {
			cand = fmt.Sprintf("%s-%d", base, i)
		}
		taken, err := skills().SlugTaken(ctx, sess, cand)
		if err != nil {
			return "", err
		}
		if !taken {
			return cand, nil
		}
	}
	return "", &domain.SkillValueError{Msg: fmt.Sprintf("Exhausted collision suffixes (-2..-999) for slug base '%s'", base)}
}

// skillNew is what _create_with_package writes: the row, then its package.
type skillNew struct {
	name, sourceType    string
	description, srcURL *string
	files               domain.SkillFiles
}

// create is _create_with_package plus the owner grant and the skill.create audit.
func (k *Skills) create(ctx context.Context, c authn.Caller, n skillNew) (SkillView, error) {
	if _, err := k.store(); err != nil {
		return SkillView{}, err
	}
	id := uuid.New()
	var out domain.Skill
	err := k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		slug, err := k.uniqueSlug(ctx, sess, n.name)
		if err != nil {
			return err
		}
		if err := skills().Insert(ctx, sess, store.SkillNew{ID: id, Name: n.name, Slug: slug, Description: n.description,
			SourceType: n.sourceType, SourceURL: n.srcURL, CreatedBy: c.UserID}, k.s.d.Now()); err != nil {
			return err
		}
		s3, err := k.storeWorkspacePackage(ctx, n.files, c.Workspace.ID())
		if err != nil {
			return err
		}
		if ok, err := k.setPackage(ctx, sess, c.UserID, id, s3, "create", nil, nil, false); err != nil || !ok {
			if err == nil {
				err = errors.New("failed to update skill package path")
			}
			return err
		}
		var ok bool
		if out, ok, err = k.get(ctx, sess, id); err != nil || !ok {
			if err == nil {
				err = errors.New("skill vanished after its create")
			}
			return err
		}
		k.s.Audit(ctx, sess, c, "skill.create", "skill", id.String())
		return authz.GrantResourceOwner(ctx, k.s.d.Graph, id.String(), c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations())
	})
	return view(out), err
}

func firstSet(override *string, parsed *string) *string {
	if override != nil && *override != "" {
		return override
	}
	return parsed
}

func nameOf(override *string, parsed string) string {
	if override != nil && *override != "" {
		return *override
	}
	return parsed
}

// CreateFromContent is create_from_content.
func (k *Skills) CreateFromContent(ctx context.Context, c authn.Caller, content string, name, description *string) (SkillView, error) {
	parsed, err := SkillParse(content)
	if err != nil {
		return SkillView{}, err
	}
	n, err := domain.SkillCheckedName(nameOf(name, parsed.Name))
	if err != nil {
		return SkillView{}, err
	}
	return k.create(ctx, c, skillNew{name: n, description: firstSet(description, parsed.Description), sourceType: domain.SkillSourceContent,
		files: domain.SkillFiles{{Path: domain.SkillManifest, Data: []byte(content)}}})
}

func (k *Skills) fromZip(data []byte, name, description *string) (string, *string, domain.SkillFiles, error) {
	md, err := domain.SkillMainFromZip(data)
	if err != nil {
		return "", nil, nil, err
	}
	parsed, err := SkillParse(md)
	if err != nil {
		return "", nil, nil, err
	}
	n, err := domain.SkillCheckedName(nameOf(name, parsed.Name))
	if err != nil {
		return "", nil, nil, err
	}
	files, err := domain.SkillFilesFromZip(data)
	if err != nil {
		return "", nil, nil, err
	}
	return n, firstSet(description, parsed.Description), files, nil
}

// CreateFromZip is create_from_zip.
func (k *Skills) CreateFromZip(ctx context.Context, c authn.Caller, data []byte, name, description *string) (SkillView, error) {
	n, d, files, err := k.fromZip(data, name, description)
	if err != nil {
		return SkillView{}, err
	}
	return k.create(ctx, c, skillNew{name: n, description: d, sourceType: domain.SkillSourceZip, files: files})
}

func (k *Skills) requireGitHubImport(ctx context.Context, c authn.Caller) error {
	if k.policy == nil {
		return &UnwiredError{Feature: "the catalog install policy"}
	}
	return k.policy.RequireAllowed(ctx, c, SkillGitHubRegistryID, SkillGitHubTrust)
}

// CreateFromGitHub is create_from_github: the policy, the repository, then the package the URL points at.
func (k *Skills) CreateFromGitHub(ctx context.Context, c authn.Caller, githubURL string, name, description *string) (SkillView, error) {
	if err := k.requireGitHubImport(ctx, c); err != nil {
		return SkillView{}, err
	}
	info, err := domain.SkillParseGitHubURL(githubURL)
	if err != nil {
		return SkillView{}, err
	}
	repoZip, err := k.downloadRepo(ctx, githubURL)
	if err != nil {
		return SkillView{}, err
	}
	sub := ""
	if info.Path != nil {
		sub = *info.Path
	}
	pkg, err := domain.SkillExtractPackage(repoZip, sub)
	if err != nil {
		return SkillView{}, err
	}
	n, d, files, err := k.fromZip(pkg, name, description)
	if err != nil {
		return SkillView{}, err
	}
	return k.create(ctx, c, skillNew{name: n, description: d, sourceType: domain.SkillSourceGitHub, srcURL: &githubURL, files: files})
}

// writeOwnPackage is _write_own_package: files as a new package of the workspace's own, recorded as an edit.
func (k *Skills) writeOwnPackage(ctx context.Context, sess db.Session, c authn.Caller, id uuid.UUID, files domain.SkillFiles) error {
	s3, err := k.storeWorkspacePackage(ctx, files, c.Workspace.ID())
	if err != nil {
		return err
	}
	ok, err := k.setPackage(ctx, sess, c.UserID, id, s3, "edit", nil, nil, false)
	if err == nil && !ok {
		err = errors.New("failed to update skill content")
	}
	return err
}

// setContent is _set_content_audited: the package's SKILL.md replaced, the other files kept.
func (k *Skills) setContent(ctx context.Context, sess db.Session, c authn.Caller, id uuid.UUID, content string) (bool, error) {
	sk, ok, err := k.get(ctx, sess, id)
	if err != nil || !ok {
		return false, err
	}
	files, err := k.readFiles(ctx, sess, c.UserID, &sk, true)
	if err != nil {
		return false, err
	}
	main, has := domain.SkillMainFile(files.Paths())
	if !has {
		main = domain.SkillManifest
	}
	files.Set(main, []byte(content))
	if err := k.writeOwnPackage(ctx, sess, c, id, files); err != nil {
		return false, err
	}
	k.s.Audit(ctx, sess, c, "skill.update", "skill", id.String())
	return true, nil
}

// Update is update_skill: the edit check, the metadata patch, then the content.
func (k *Skills) Update(ctx context.Context, c authn.Caller, id uuid.UUID, name, description, content *string) (SkillView, error) {
	if err := k.s.Require(ctx, c, "edit", id); err != nil {
		return SkillView{}, err
	}
	if content != nil {
		if _, err := k.store(); err != nil {
			return SkillView{}, err
		}
	}
	var out domain.Skill
	err := k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if _, ok, err := k.get(ctx, sess, id); err != nil || !ok {
			if err == nil {
				err = ErrSkillNotFound
			}
			return err
		}
		if name != nil || description != nil {
			if err := skills().UpdateMeta(ctx, sess, id, name, description, nil, k.s.d.Now()); err != nil {
				return err
			}
		}
		k.s.Audit(ctx, sess, c, "skill.update", "skill", id.String())
		if content != nil {
			if ok, err := k.setContent(ctx, sess, c, id, *content); err != nil || !ok {
				if err == nil {
					err = ErrSkillNotFound
				}
				return err
			}
		}
		var ok bool
		var err error
		if out, ok, err = k.get(ctx, sess, id); err == nil && !ok {
			err = ErrSkillNotFound
		}
		return err
	})
	return view(out), err
}

// Delete is delete_skill: the delete check, the own copy's objects, the row and its tuples.
func (k *Skills) Delete(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	if err := k.s.Require(ctx, c, "delete", id); err != nil {
		return err
	}
	deleted, err := k.delete(ctx, c, id)
	if err != nil {
		return err
	}
	if !deleted {
		return ErrSkillNotFound
	}
	return nil
}

func (k *Skills) delete(ctx context.Context, c authn.Caller, id uuid.UUID) (bool, error) {
	var deleted bool
	err := k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		sk, ok, err := k.get(ctx, sess, id)
		if err != nil || !ok {
			return err
		}
		if domain.SkillIsOwnCopy(sk) && k.blob != nil {
			if _, err := k.deletePackage(ctx, *sk.S3Path); err != nil {
				k.warn(ctx, "Failed to delete S3 package for skill", "skill_id", id.String(), "error", err.Error())
			}
		}
		if deleted, err = skills().Delete(ctx, sess, id); err != nil {
			return err
		}
		k.s.Audit(ctx, sess, c, "skill.delete", "skill", id.String())
		return nil
	})
	if err != nil || !deleted {
		return deleted, err
	}
	if rw, ok := k.s.d.Graph.(authz.ReadWriter); ok {
		if err := authz.RevokeResource(ctx, rw, id.String()); err != nil {
			k.warn(ctx, "revoking a deleted skill's tuples failed", "skill_id", id.String(), "error", err.Error())
		}
	}
	return true, nil
}

func (k *Skills) warn(ctx context.Context, msg string, args ...any) {
	if k.s.d.Log != nil {
		k.s.d.Log.WarnContext(ctx, msg, args...)
	}
}

// Versions is list_skill_versions: every package the skill pointed at, oldest first.
func (k *Skills) Versions(ctx context.Context, c authn.Caller, id uuid.UUID) ([]SkillVersionView, error) {
	if err := k.s.Require(ctx, c, "read", id); err != nil {
		return nil, err
	}
	var out []SkillVersionView
	err := k.s.read(ctx, c.Workspace, func(sess db.Session) error {
		sk, ok, err := k.get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return ErrSkillNotFound
		}
		current := sk.S3Path
		if _, err := k.resolve(ctx, sess, c.UserID, &sk, false); err != nil {
			return skillUncaught(err)
		}
		vs, err := skills().Versions(ctx, sess, id)
		if err != nil {
			return err
		}
		for i, v := range vs {
			out = append(out, SkillVersionView{SkillVersion: v, Current: i == len(vs)-1 && current != nil && v.S3Path == *current})
		}
		return nil
	})
	return out, err
}

// Rollback is rollback: the skill points at a version's package again, recorded as a new version.
func (k *Skills) Rollback(ctx context.Context, c authn.Caller, id, versionID uuid.UUID) (SkillView, error) {
	if err := k.s.Require(ctx, c, "edit", id); err != nil {
		return SkillView{}, err
	}
	var out domain.Skill
	err := k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		sk, ok, err := k.get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return ErrSkillNotFound
		}
		v, ok, err := skills().Version(ctx, sess, id, versionID)
		if err != nil {
			return err
		}
		if !ok {
			return ErrSkillVersionNotFound
		}
		if domain.SkillIsCatalogPackage(v.S3Path) && sk.RegistryItemID != nil {
			if k.catalog == nil {
				return k.unwiredCatalog()
			}
			if err := k.catalog.Pin(ctx, c, id, *sk.RegistryItemID, v.CatalogVersion); err != nil {
				return err
			}
		}
		moved, err := k.setPackage(ctx, sess, c.UserID, id, v.S3Path, "rollback", v.CatalogVersion, nil, false)
		if err != nil {
			return err
		}
		if !moved {
			return ErrSkillNotFound
		}
		if out, ok, err = k.get(ctx, sess, id); err == nil && !ok {
			err = ErrSkillNotFound
		}
		if err != nil {
			return err
		}
		k.s.Audit(ctx, sess, c, "skill.update", "skill", id.String())
		return nil
	})
	return view(out), err
}

// Install is install_skill: a tenant skill as it is, a catalog item forked.
func (k *Skills) Install(ctx context.Context, c authn.Caller, id uuid.UUID) (SkillView, error) {
	var sk domain.Skill
	var ok bool
	if err := k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		sk, ok, err = k.get(ctx, sess, id)
		return err
	}); err != nil {
		return SkillView{}, err
	}
	if !ok {
		var found bool
		var err error
		if sk, found, err = k.installItem(ctx, c, id); err != nil {
			return SkillView{}, err
		}
		if !found {
			return SkillView{}, ErrSkillNotFound
		}
	}
	if sk.CreatedBy == c.UserID {
		if err := authz.GrantResourceOwner(ctx, k.s.d.Graph, sk.ID, c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations()); err != nil {
			return SkillView{}, err
		}
	}
	return view(sk), nil
}

// UpdateInstalled is update_installed_skill (admin).
func (k *Skills) UpdateInstalled(ctx context.Context, c authn.Caller, id uuid.UUID, discard bool) (SkillView, error) {
	if err := k.s.RequireAdmin(ctx); err != nil {
		return SkillView{}, err
	}
	if k.catalog == nil {
		return SkillView{}, k.unwiredCatalog()
	}
	v, ok, err := k.catalog.Update(ctx, c, id, discard)
	if err != nil {
		return SkillView{}, err
	}
	if !ok {
		return SkillView{}, ErrSkillNotFound
	}
	return v, nil
}

// UpdateAll is update_all_skills (admin).
func (k *Skills) UpdateAll(ctx context.Context, c authn.Caller) ([]SkillUpdateResult, error) {
	if err := k.s.RequireAdmin(ctx); err != nil {
		return nil, err
	}
	if k.catalog == nil {
		return nil, k.unwiredCatalog()
	}
	return k.catalog.UpdateAll(ctx, c)
}

// Content is get_skill_content: the skill's SKILL.md.
func (k *Skills) Content(ctx context.Context, c authn.Caller, id uuid.UUID) (SkillView, string, error) {
	var sk domain.Skill
	var text string
	err := k.s.read(ctx, c.Workspace, func(sess db.Session) error {
		var ok bool
		var err error
		if sk, ok, err = k.get(ctx, sess, id); err != nil {
			return err
		}
		if !ok {
			return ErrSkillNotFound
		}
		text, err = k.readSkillMD(ctx, sess, c.UserID, &sk, false)
		return skillUncaught(err)
	})
	return view(sk), text, err
}

func skillFilesError(err error) error {
	var ve *domain.SkillValueError
	if errors.As(err, &ve) {
		return &SkillFilesError{Msg: ve.Msg}
	}
	return err
}

// Files is list_skill_files.
func (k *Skills) Files(ctx context.Context, c authn.Caller, id uuid.UUID, includeURLs bool) ([]SkillFileView, error) {
	var out []SkillFileView
	err := k.s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		out, err = k.files(ctx, sess, c, id, includeURLs)
		return err
	})
	return out, skillFilesError(err)
}

func (k *Skills) files(ctx context.Context, sess db.Session, c authn.Caller, id uuid.UUID, includeURLs bool) ([]SkillFileView, error) {
	sk, ok, err := k.get(ctx, sess, id)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, &domain.SkillValueError{Msg: "Skill not found: " + id.String()}
	}
	s3, err := k.resolve(ctx, sess, c.UserID, &sk, false)
	if err != nil {
		return nil, err
	}
	infos, err := k.listFiles(ctx, s3)
	if err != nil {
		return nil, err
	}
	out := make([]SkillFileView, 0, len(infos))
	for _, f := range infos {
		v := SkillFileView{Path: f.Path, Size: f.Size}
		if includeURLs {
			u, err := k.fileURL(ctx, s3, f.Path, skillURLTTL)
			if err != nil {
				return nil, err
			}
			v.URL = &u
		}
		out = append(out, v)
	}
	return out, nil
}

// FileURL is get_skill_file: a presigned URL to one file of the package.
func (k *Skills) FileURL(ctx context.Context, c authn.Caller, id uuid.UUID, path string) (string, error) {
	var u string
	err := k.s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		u, err = k.fileURLIn(ctx, sess, c, id, path, skillURLTTL)
		return err
	})
	return u, skillFilesError(err)
}

func (k *Skills) fileURLIn(ctx context.Context, sess db.Session, c authn.Caller, id uuid.UUID, path string, ttl time.Duration) (string, error) {
	sk, ok, err := k.get(ctx, sess, id)
	if err != nil {
		return "", err
	}
	if !ok {
		return "", &domain.SkillValueError{Msg: "Skill not found: " + id.String()}
	}
	s3, err := k.resolve(ctx, sess, c.UserID, &sk, false)
	if err != nil {
		return "", err
	}
	return k.fileURL(ctx, s3, path, ttl)
}

// requireSkill is _require_skill: a bundle end in this workspace.
func requireSkill(ctx context.Context, sess db.Session, id uuid.UUID) error {
	_, ok, err := skills().Get(ctx, sess, id)
	if err == nil && !ok {
		err = &SkillNotFoundError{}
	}
	return err
}

// AddMember is add_skill_member after the edit check.
func (k *Skills) AddMember(ctx context.Context, c authn.Caller, m domain.SkillMember) (domain.SkillMember, error) {
	parent, child := uuid.MustParse(m.ParentSkillID), uuid.MustParse(m.ChildSkillID)
	if err := k.s.Require(ctx, c, "edit", parent); err != nil {
		return domain.SkillMember{}, err
	}
	if parent == child {
		return domain.SkillMember{}, &domain.SkillValueError{Msg: "A skill cannot be a member of itself"}
	}
	if m.Dependencies == nil {
		m.Dependencies = []string{}
	}
	err := k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := requireSkill(ctx, sess, parent); err != nil {
			return err
		}
		if err := requireSkill(ctx, sess, child); err != nil {
			return err
		}
		existing, err := skills().Members(ctx, sess, parent)
		if err != nil {
			return err
		}
		test := make([]domain.SkillMemberDeps, 0, len(existing)+1)
		for _, e := range existing {
			test = append(test, domain.SkillMemberDeps{Child: e.ChildSkillID, Dependencies: e.Dependencies})
		}
		test = append(test, domain.SkillMemberDeps{Child: child.String(), Dependencies: m.Dependencies})
		if _, err := domain.SkillTopoSort(test); err != nil {
			return &domain.SkillValueError{Msg: fmt.Sprintf("Adding skill %s would create a cycle", child)}
		}
		return skills().PutMember(ctx, sess, m)
	})
	return m, err
}

// Members is list_skill_members.
func (k *Skills) Members(ctx context.Context, c authn.Caller, parent uuid.UUID) ([]domain.SkillMember, error) {
	var out []domain.SkillMember
	err := k.s.read(ctx, c.Workspace, func(sess db.Session) error {
		if err := requireSkill(ctx, sess, parent); err != nil {
			return err
		}
		var err error
		out, err = skills().Members(ctx, sess, parent)
		return err
	})
	return out, err
}

// RemoveMember is remove_skill_member after the edit check.
func (k *Skills) RemoveMember(ctx context.Context, c authn.Caller, parent, child uuid.UUID) error {
	if err := k.s.Require(ctx, c, "edit", parent); err != nil {
		return err
	}
	return k.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := requireSkill(ctx, sess, parent); err != nil {
			return err
		}
		removed, err := skills().RemoveMember(ctx, sess, parent, child)
		if err == nil && !removed {
			err = &SkillMemberNotFoundError{}
		}
		return err
	})
}

// Flatten is flatten_skill_members: the children in execution order.
func (k *Skills) Flatten(ctx context.Context, c authn.Caller, parent uuid.UUID) ([]string, error) {
	var out []string
	err := k.s.read(ctx, c.Workspace, func(sess db.Session) error {
		if err := requireSkill(ctx, sess, parent); err != nil {
			return err
		}
		members, err := skills().Members(ctx, sess, parent)
		if err != nil {
			return err
		}
		deps := make([]domain.SkillMemberDeps, len(members))
		for i, m := range members {
			deps[i] = domain.SkillMemberDeps{Child: m.ChildSkillID, Dependencies: m.Dependencies}
		}
		out, err = domain.SkillTopoSort(deps)
		return err
	})
	return out, err
}
