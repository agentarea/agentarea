package service

import (
	"context"
	"errors"
	"slices"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
)

// BundleProjects is what a bundle deploy reads and writes of projects.
type BundleProjects struct{ S *Service }

var _ catalogapi.BundleProjects = BundleProjects{}

func projectRefusal(err error) error {
	var nf *domain.NotFoundError
	if errors.As(err, &nf) {
		return &catalogapi.BundleRefusal{Msg: nf.Error()}
	}
	return err
}

func links(spec catalogapi.BundleProjectSpec) map[domain.LinkKind][]string {
	return map[domain.LinkKind][]string{domain.LinkAgent: spec.AgentIDs, domain.LinkMCPInstance: spec.MCPInstanceIDs, domain.LinkSkill: spec.SkillIDs}
}

func linkKinds() []domain.LinkKind {
	return []domain.LinkKind{domain.LinkAgent, domain.LinkMCPInstance, domain.LinkSkill}
}

func (b BundleProjects) ProjectName(ctx context.Context, c authn.Caller, id string) (string, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return "", false, nil
	}
	p, err := b.S.Get(ctx, c.Workspace, u)
	switch {
	case errors.Is(err, domain.ErrProjectNotFound):
		return "", false, nil
	case err != nil:
		return "", false, err
	}
	return p.Name, true, nil
}

func (b BundleProjects) link(ctx context.Context, c authn.Caller, project uuid.UUID, spec catalogapi.BundleProjectSpec) error {
	want := links(spec)
	for _, k := range linkKinds() {
		for _, child := range want[k] {
			if err := b.S.Link(ctx, c.Workspace, k, project, child); err != nil {
				return projectRefusal(err)
			}
		}
	}
	return nil
}

func (b BundleProjects) CreateProject(ctx context.Context, c authn.Caller, spec catalogapi.BundleProjectSpec) (string, error) {
	p, err := b.S.Create(ctx, c.Workspace, c.UserID, domain.New{Name: spec.Name, Description: spec.Description, Instructions: spec.Instructions})
	if err != nil {
		return "", projectRefusal(err)
	}
	id := uuid.MustParse(p.ID)
	if err := b.link(ctx, c, id, spec); err != nil {
		return "", errors.Join(err, b.S.Delete(context.WithoutCancel(ctx), c.Workspace, id))
	}
	return p.ID, nil
}

func (b BundleProjects) UpdateProject(ctx context.Context, c authn.Caller, id string, spec, managed catalogapi.BundleProjectSpec) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return catalogapi.ErrBundleEntityGone
	}
	name := spec.Name
	_, err = b.S.Update(ctx, c.Workspace, u, domain.Patch{Name: &name, Description: domain.Field{Set: true, Value: spec.Description},
		Instructions: domain.Field{Set: true, Value: spec.Instructions}})
	if errors.Is(err, domain.ErrProjectNotFound) {
		return catalogapi.ErrBundleEntityGone
	}
	if err != nil {
		return projectRefusal(err)
	}
	if err := b.link(ctx, c, u, spec); err != nil {
		return err
	}
	want, had := links(spec), links(managed)
	for _, k := range linkKinds() {
		for _, child := range had[k] {
			cu, err := uuid.Parse(child)
			if err != nil || slices.Contains(want[k], child) {
				continue
			}
			if err := b.S.Unlink(ctx, c.Workspace, k, u, cu); err != nil {
				return projectRefusal(err)
			}
		}
	}
	return nil
}

func (b BundleProjects) DeleteProject(ctx context.Context, c authn.Caller, id string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	return b.S.Delete(ctx, c.Workspace, u)
}
