package service

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// RunSkills implements api.RunSkills over the skill service.
type RunSkills struct{ K *Skills }

var _ api.RunSkills = RunSkills{}

// runSkill is what deciding on and offering a skill reads of its row.
type runSkill struct {
	ID, Name, Description, SourceType, Package string
	RegistryItemID                             string
}

func runSkillOf(sk domain.Skill) runSkill {
	return runSkill{ID: sk.ID, Name: sk.Name, Description: str(sk.Description), SourceType: sk.SourceType,
		Package: str(sk.S3Path), RegistryItemID: str(sk.RegistryItemID)}
}

func runSkillOfRef(sk domain.SkillRef) runSkill {
	return runSkill{ID: sk.ID, Name: sk.Name, Description: str(sk.Description), SourceType: sk.SourceType,
		Package: str(sk.Package), RegistryItemID: str(sk.RegistryItemID)}
}

// refusals is run_refusals: why the workspace's install rules keep a run from
// each skill, by id. A skill the workspace wrote is not asked about, nor an
// install whose catalog item is gone.
func (k *Skills) refusals(ctx context.Context, ws scope.Workspace, skills []runSkill) (map[string]string, error) {
	var items []string
	for _, s := range skills {
		if s.RegistryItemID != "" {
			items = append(items, s.RegistryItemID)
		}
	}
	var provenance map[string]catalogapi.ItemSource
	if len(items) > 0 {
		if k.items == nil {
			return nil, k.unwiredCatalog()
		}
		var err error
		if provenance, err = k.items.SkillProvenance(ctx, ws, items); err != nil {
			return nil, err
		}
	}
	sources := map[string]SkillSource{}
	for _, s := range skills {
		switch {
		case s.RegistryItemID != "":
			if src, ok := provenance[s.RegistryItemID]; ok {
				sources[s.ID] = SkillSource{RegistryID: src.RegistryID, Trust: src.Trust}
			}
		case s.SourceType == domain.SkillSourceGitHub:
			sources[s.ID] = SkillSource{RegistryID: SkillGitHubRegistryID, Trust: SkillGitHubTrust}
		}
	}
	out := map[string]string{}
	if len(sources) == 0 {
		return out, nil
	}
	if k.policy == nil {
		return nil, &UnwiredError{Feature: "the catalog install policy"}
	}
	for id, src := range sources {
		reason, refused, err := k.policy.RunRefusal(ctx, ws, src.RegistryID, src.Trust)
		if err != nil {
			return nil, err
		}
		if refused {
			out[id] = reason
		}
	}
	return out, nil
}

// refusedOrUnwired makes a policy that cannot be asked a final refusal of the run's skill.
func refusedOrUnwired(err error) error {
	var unwired *UnwiredError
	if errors.As(err, &unwired) {
		return fmt.Errorf("%w: %s", api.ErrSkillRefused, unwired.Error())
	}
	return err
}

// Offered is _resolve_task_resources' skills and _runnable_skills.
func (r RunSkills) Offered(ctx context.Context, ws scope.Workspace, agentID string, selected []string) ([]runsapi.Skill, []runsapi.WithheldSkill, error) {
	agent, err := uuid.Parse(agentID)
	if err != nil {
		return nil, nil, api.ErrNotFound
	}
	var skills []runSkill
	err = r.K.s.read(ctx, ws, func(sess db.Session) error {
		refs, err := r.K.s.store.Skills(ctx, sess, agent)
		if err != nil {
			return err
		}
		for _, ref := range refs {
			skills = append(skills, runSkillOfRef(ref))
		}
		var seen []uuid.UUID
		for _, raw := range selected {
			id, err := uuid.Parse(raw)
			if err != nil {
				return fmt.Errorf("%w: Invalid task skills reference", api.ErrSkillNotFound)
			}
			if slices.Contains(seen, id) || slices.ContainsFunc(skills, func(s runSkill) bool { return s.ID == id.String() }) {
				continue
			}
			seen = append(seen, id)
			row, ok, err := r.K.get(ctx, sess, id)
			if err != nil {
				return err
			}
			if !ok {
				return fmt.Errorf("%w: Selected task skill is unavailable", api.ErrSkillNotFound)
			}
			sk := runSkillOf(row)
			refused, err := r.K.refusals(ctx, ws, []runSkill{sk})
			if err != nil {
				return refusedOrUnwired(err)
			}
			if reason, ok := refused[sk.ID]; ok {
				return fmt.Errorf("%w: Refused by policy: %s", api.ErrSkillRefused, reason)
			}
			if slices.ContainsFunc(skills, func(s runSkill) bool { return s.Name == sk.Name }) {
				return fmt.Errorf("%w: Selected task skills must have distinct names", api.ErrSkillRefused)
			}
			skills = append(skills, sk)
		}
		return nil
	})
	if err != nil {
		return nil, nil, err
	}
	refused, err := r.K.refusals(ctx, ws, skills)
	if err != nil {
		return nil, nil, refusedOrUnwired(err)
	}
	offered := []runsapi.Skill{}
	withheld := []runsapi.WithheldSkill{}
	for _, s := range skills {
		if reason, ok := refused[s.ID]; ok {
			if r.K.s.d.Log != nil {
				r.K.s.d.Log.WarnContext(ctx, "skill is not offered to this run", "skill", s.Name, "skill_id", s.ID, "reason", reason)
			}
			withheld = append(withheld, runsapi.WithheldSkill{ID: s.ID, Name: s.Name, Reason: reason})
			continue
		}
		offered = append(offered, runsapi.Skill{ID: s.ID, Name: s.Name, Description: s.Description, Package: s.Package})
	}
	return offered, withheld, nil
}

// row is the skill's row in the workspace, ErrSkillNotFound when it is gone.
func (r RunSkills) row(ctx context.Context, sess db.Session, skill runsapi.Skill) (domain.Skill, error) {
	id, err := uuid.Parse(skill.ID)
	if err != nil {
		return domain.Skill{}, api.ErrSkillNotFound
	}
	sk, ok, err := r.K.get(ctx, sess, id)
	if err != nil {
		return domain.Skill{}, &api.SkillUnreachableError{Service: "Database", Err: err}
	}
	if !ok {
		return domain.Skill{}, api.ErrSkillNotFound
	}
	return sk, nil
}

// Allow is get_with_catalog(to_run=True) as activation asks it.
func (r RunSkills) Allow(ctx context.Context, ws scope.Workspace, skill runsapi.Skill) error {
	return r.K.s.read(ctx, ws, func(sess db.Session) error {
		sk, err := r.row(ctx, sess, skill)
		if err != nil {
			return err
		}
		refused, err := r.K.refusals(ctx, ws, []runSkill{runSkillOf(sk)})
		if err != nil {
			return refusedOrUnwired(err)
		}
		if reason, ok := refused[sk.ID]; ok {
			return fmt.Errorf("%w: Refused by policy: %s", api.ErrSkillRefused, reason)
		}
		return nil
	})
}

// packageAt is _package_of: the package the run was configured with when the
// skill may be read from it, else the skill's own.
func (r RunSkills) packageAt(ctx context.Context, sess db.Session, sk *domain.Skill, at string) (string, error) {
	if at == "" || sk.Content != nil {
		return r.K.resolve(ctx, sess, "", sk, false)
	}
	areas := []string{domain.SkillsPrefix + "/catalog/", domain.SkillsPrefix + "/" + SkillPlatformWorkspace + "/"}
	if sk.WorkspaceID != "" {
		areas = append(areas, domain.SkillsPrefix+"/"+sk.WorkspaceID+"/")
	}
	if slices.Contains(strings.Split(at, "/"), "..") || strings.Contains(at, "\\") ||
		!slices.ContainsFunc(areas, func(a string) bool { return strings.HasPrefix(at, a) }) {
		return "", &domain.SkillValueError{Msg: fmt.Sprintf("Skill %s cannot be read from package %q", sk.ID, at)}
	}
	return at, nil
}

// readFailure sorts a package read's failure: storage that did not answer is
// an outage; a package that cannot be read is a refusal.
func readFailure(err error) error {
	var ve *domain.SkillValueError
	var ie *skillInternalError
	var nf *SkillFileNotFoundError
	switch {
	case err == nil:
		return nil
	case errors.Is(err, api.ErrSkillNotFound), errors.Is(err, api.ErrSkillRefused):
		return err
	case errors.As(err, &ve), errors.As(err, &ie), errors.As(err, &nf), errors.Is(err, blob.ErrNotFound):
		return fmt.Errorf("%w: %s", api.ErrSkillRefused, err.Error())
	}
	var unwired *UnwiredError
	if errors.As(err, &unwired) {
		return fmt.Errorf("%w: %s", api.ErrSkillRefused, unwired.Error())
	}
	return &api.SkillUnreachableError{Service: "Object storage", Err: err}
}

// ReadSkillMD is read_skill_md(skill, at=package).
func (r RunSkills) ReadSkillMD(ctx context.Context, ws scope.Workspace, skill runsapi.Skill) (string, error) {
	var out string
	err := r.K.s.read(ctx, ws, func(sess db.Session) error {
		sk, err := r.row(ctx, sess, skill)
		if err != nil {
			return err
		}
		if sk.Content != nil {
			out = *sk.Content
			return nil
		}
		s3, err := r.packageAt(ctx, sess, &sk, skill.Package)
		if err != nil {
			return readFailure(err)
		}
		files, err := r.K.readPackage(ctx, s3)
		if err != nil {
			return readFailure(err)
		}
		main, ok := domain.SkillMainFile(files.Paths())
		if !ok {
			return readFailure(&skillInternalError{msg: fmt.Sprintf("Skill %s package has no SKILL.md at its root", sk.ID)})
		}
		data, _ := files.Get(main)
		text, err := domain.SkillDecodeUTF8(data)
		if err != nil {
			return readFailure(&skillInternalError{msg: err.Error()})
		}
		out = text
		return nil
	})
	return out, err
}

// PackageFiles is read_files(skill, at=package).
func (r RunSkills) PackageFiles(ctx context.Context, ws scope.Workspace, skill runsapi.Skill) ([]api.SkillPackageFile, error) {
	var out []api.SkillPackageFile
	err := r.K.s.read(ctx, ws, func(sess db.Session) error {
		sk, err := r.row(ctx, sess, skill)
		if err != nil {
			return err
		}
		var files domain.SkillFiles
		if sk.Content != nil {
			files, err = r.K.unmovedFiles(ctx, &sk)
		} else {
			var s3 string
			if s3, err = r.packageAt(ctx, sess, &sk, skill.Package); err == nil {
				files, err = r.K.readPackage(ctx, s3)
			}
		}
		if err != nil {
			return readFailure(err)
		}
		for _, f := range files {
			out = append(out, api.SkillPackageFile{Path: f.Path, Data: f.Data})
		}
		return nil
	})
	return out, err
}
