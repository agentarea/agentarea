package service

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

// SkillToolset is api.Skills over the skills service.
type SkillToolset struct{ K *Skills }

var _ api.Skills = SkillToolset{}

func skillSummary(sk domain.Skill) api.SkillSummary {
	out := api.SkillSummary{ID: sk.ID, Name: sk.Name, Slug: sk.Slug, Description: sk.Description, SourceType: sk.SourceType, SourceURL: sk.SourceURL}
	if sk.S3Path != nil {
		out.Package = *sk.S3Path
	}
	return out
}

func skillID(id string) (uuid.UUID, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return uuid.Nil, api.ErrSkillNotFound
	}
	return u, nil
}

// List is skills_list: the workspace's skills the caller may read.
func (t SkillToolset) List(ctx context.Context, c authn.Caller) ([]api.SkillSummary, error) {
	readable, err := authz.ReadableResourceIDs(ctx, t.K.s.d.Graph, c.GraphSubject())
	if err != nil {
		return nil, err
	}
	var all []domain.Skill
	if err := t.K.s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		all, err = skills().All(ctx, sess)
		return err
	}); err != nil {
		return nil, err
	}
	out := []api.SkillSummary{}
	for _, sk := range all {
		if _, ok := readable[sk.ID]; ok {
			out = append(out, skillSummary(sk))
		}
	}
	return out, nil
}

// Get is skills_get.
func (t SkillToolset) Get(ctx context.Context, c authn.Caller, id string) (api.SkillDetail, error) {
	u, err := skillID(id)
	if err != nil {
		return api.SkillDetail{}, err
	}
	if err := t.K.s.Require(ctx, c, "read", u); err != nil {
		return api.SkillDetail{}, err
	}
	var out api.SkillDetail
	err = t.K.s.read(ctx, c.Workspace, func(sess db.Session) error {
		sk, ok, err := t.K.get(ctx, sess, u)
		if err != nil {
			return err
		}
		if !ok {
			return api.ErrSkillNotFound
		}
		text, err := t.K.readSkillMD(ctx, sess, c.UserID, &sk, false)
		out = api.SkillDetail{SkillSummary: skillSummary(sk), Content: text}
		return err
	})
	return out, err
}

func skillZipOf(files []api.SkillFileText) ([]byte, error) {
	var fs domain.SkillFiles
	for _, f := range files {
		fs.Set(f.Path, []byte(f.Text))
	}
	return domain.SkillZip(fs)
}

// CreateFromFiles is skills_create: the files zipped, then create_from_zip.
func (t SkillToolset) CreateFromFiles(ctx context.Context, c authn.Caller, files []api.SkillFileText, in api.SkillCreate) (api.SkillSummary, error) {
	data, err := skillZipOf(files)
	if err != nil {
		return api.SkillSummary{}, err
	}
	return t.CreateFromArchive(ctx, c, data, in)
}

// CreateFromArchive is skills_create_from_archive.
func (t SkillToolset) CreateFromArchive(ctx context.Context, c authn.Caller, zip []byte, in api.SkillCreate) (api.SkillSummary, error) {
	n, d, files, err := t.K.fromZip(zip, in.Name, in.Description)
	if err != nil {
		return api.SkillSummary{}, err
	}
	v, err := t.K.create(ctx, c, skillNew{name: n, description: d, sourceType: domain.SkillSourceZip, srcURL: in.SourceURL, files: files})
	return skillSummary(v.Skill), err
}

// DownloadGitHubRepo is the import's policy check and repository download.
func (t SkillToolset) DownloadGitHubRepo(ctx context.Context, c authn.Caller, githubURL string) ([]byte, error) {
	if err := t.K.requireGitHubImport(ctx, c); err != nil {
		return nil, err
	}
	return t.K.downloadRepo(ctx, githubURL)
}

// ExtractGitHubPackage is extract_skill_package.
func (SkillToolset) ExtractGitHubPackage(repoZip []byte, packagePath string) ([]byte, error) {
	return domain.SkillExtractPackage(repoZip, packagePath)
}

func (t SkillToolset) after(ctx context.Context, c authn.Caller, u uuid.UUID) (api.SkillSummary, error) {
	var out api.SkillSummary
	err := t.K.s.read(ctx, c.Workspace, func(sess db.Session) error {
		sk, ok, err := t.K.get(ctx, sess, u)
		if err == nil && !ok {
			err = api.ErrSkillNotFound
		}
		out = skillSummary(sk)
		return err
	})
	return out, err
}

// EditMetadata is skills_edit_metadata.
func (t SkillToolset) EditMetadata(ctx context.Context, c authn.Caller, id string, name, description *string) (api.SkillSummary, error) {
	u, err := skillID(id)
	if err != nil {
		return api.SkillSummary{}, err
	}
	v, err := t.K.Update(ctx, c, u, name, description, nil)
	if errors.Is(err, ErrSkillNotFound) {
		err = api.ErrSkillNotFound
	}
	return skillSummary(v.Skill), err
}

// SetContent is skills_edit_content for a single SKILL.md.
func (t SkillToolset) SetContent(ctx context.Context, c authn.Caller, id, content string) (api.SkillSummary, error) {
	u, err := skillID(id)
	if err != nil {
		return api.SkillSummary{}, err
	}
	if err := t.K.s.Require(ctx, c, "edit", u); err != nil {
		return api.SkillSummary{}, err
	}
	err = t.K.s.write(ctx, c.Workspace, func(sess db.Session) error {
		ok, err := t.K.setContent(ctx, sess, c, u, content)
		if err == nil && !ok {
			err = fmt.Errorf("skill %s not found: %w", id, api.ErrSkillNotFound)
		}
		return err
	})
	if err != nil {
		return api.SkillSummary{}, err
	}
	return t.after(ctx, c, u)
}

// ReplaceFiles is replace_package_from_files.
func (t SkillToolset) ReplaceFiles(ctx context.Context, c authn.Caller, id string, files []api.SkillFileText) (api.SkillSummary, error) {
	u, err := skillID(id)
	if err != nil {
		return api.SkillSummary{}, err
	}
	if err := t.K.s.Require(ctx, c, "edit", u); err != nil {
		return api.SkillSummary{}, err
	}
	err = t.K.s.write(ctx, c.Workspace, func(sess db.Session) error {
		sk, ok, err := t.K.get(ctx, sess, u)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.SkillValueError{Msg: "Skill not found: " + id}
		}
		var fs domain.SkillFiles
		hasMain := false
		for _, f := range files {
			if l := strings.ToLower(f.Path); l == "skill.md" || l == "skill.markdown" {
				hasMain = true
			}
			fs.Set(f.Path, []byte(f.Text))
		}
		if !hasMain {
			return &domain.SkillValueError{Msg: "files must include a SKILL.md at the root"}
		}
		if _, err := t.K.resolve(ctx, sess, c.UserID, &sk, true); err != nil {
			return err
		}
		if err := t.K.writeOwnPackage(ctx, sess, c, u, fs); err != nil {
			return err
		}
		t.K.s.Audit(ctx, sess, c, "skill.update", "skill", u.String())
		return nil
	})
	if err != nil {
		return api.SkillSummary{}, err
	}
	return t.after(ctx, c, u)
}

// Delete is skills_delete.
func (t SkillToolset) Delete(ctx context.Context, c authn.Caller, id string) (bool, error) {
	u, err := skillID(id)
	if err != nil {
		return false, err
	}
	if err := t.K.s.Require(ctx, c, "delete", u); err != nil {
		return false, err
	}
	return t.K.delete(ctx, c, u)
}

// runnable is require_runnable: the install policy's say over a run reading the skill.
func (t SkillToolset) runnable(ctx context.Context, c authn.Caller, sk domain.Skill) error {
	refused, err := t.K.refusals(ctx, c.Workspace, []runSkill{runSkillOf(sk)})
	if err != nil {
		return err
	}
	if reason, ok := refused[sk.ID]; ok {
		return &PermissionError{Msg: "Refused by policy: " + reason}
	}
	return nil
}

func (t SkillToolset) runnableSkill(ctx context.Context, sess db.Session, c authn.Caller, id string) (domain.Skill, string, error) {
	u, err := skillID(id)
	if err != nil {
		return domain.Skill{}, "", &domain.SkillValueError{Msg: "Skill not found: " + id}
	}
	sk, ok, err := t.K.get(ctx, sess, u)
	if err != nil {
		return domain.Skill{}, "", err
	}
	if !ok {
		return domain.Skill{}, "", &domain.SkillValueError{Msg: "Skill not found: " + u.String()}
	}
	if err := t.runnable(ctx, c, sk); err != nil {
		return domain.Skill{}, "", err
	}
	s3, err := t.K.resolve(ctx, sess, c.UserID, &sk, false)
	return sk, s3, err
}

// ListFiles is skills_list_files.
func (t SkillToolset) ListFiles(ctx context.Context, c authn.Caller, id string, includeURLs bool) ([]api.SkillFileEntry, error) {
	var out []api.SkillFileEntry
	err := t.K.s.read(ctx, c.Workspace, func(sess db.Session) error {
		_, s3, err := t.runnableSkill(ctx, sess, c, id)
		if err != nil {
			return err
		}
		infos, err := t.K.listFiles(ctx, s3)
		if err != nil {
			return err
		}
		for _, f := range infos {
			e := api.SkillFileEntry{Path: f.Path, Size: f.Size}
			if includeURLs {
				u, err := t.K.fileURL(ctx, s3, f.Path, skillURLTTL)
				if err != nil {
					return err
				}
				e.URL = &u
			}
			out = append(out, e)
		}
		return nil
	})
	return out, err
}

// FileURL is skills_get_file with as_url.
func (t SkillToolset) FileURL(ctx context.Context, c authn.Caller, id, path string, expiresIn int) (string, error) {
	var out string
	err := t.K.s.read(ctx, c.Workspace, func(sess db.Session) error {
		_, s3, err := t.runnableSkill(ctx, sess, c, id)
		if err != nil {
			return err
		}
		out, err = t.K.fileURL(ctx, s3, path, time.Duration(expiresIn)*time.Second)
		return err
	})
	return out, err
}

// FileContent is skills_get_file's bytes.
func (t SkillToolset) FileContent(ctx context.Context, c authn.Caller, id, path string) ([]byte, error) {
	var out []byte
	err := t.K.s.read(ctx, c.Workspace, func(sess db.Session) error {
		_, s3, err := t.runnableSkill(ctx, sess, c, id)
		if err != nil {
			return err
		}
		out, err = t.K.fileContent(ctx, s3, path)
		return err
	})
	return out, err
}
