package service

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
)

// Service is ProjectService (agentarea_projects/application/service.py).
type Service struct {
	d Deps
}

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	return &Service{d: d}
}

func (s *Service) read(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

// inWorkspace is _in_workspace for a project: a malformed or unknown id is
// NotFoundError(label + " not found").
func (s *Service) inWorkspace(ctx context.Context, sess db.Session, id, label string) (uuid.UUID, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return uuid.Nil, &domain.NotFoundError{Label: label}
	}
	_, ok, err := s.d.Store.Get(ctx, sess, u)
	if err != nil {
		return uuid.Nil, err
	}
	if !ok {
		return uuid.Nil, &domain.NotFoundError{Label: label}
	}
	return u, nil
}

// Create is create_project.
func (s *Service) Create(ctx context.Context, ws scope.Workspace, userID string, n domain.New) (domain.Project, error) {
	if n.ParentProjectID != nil {
		err := s.read(ctx, ws, func(sess db.Session) error {
			_, err := s.inWorkspace(ctx, sess, *n.ParentProjectID, "Parent project")
			return err
		})
		if err != nil {
			return domain.Project{}, err
		}
	}
	var p domain.Project
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		var err error
		p, err = s.d.Store.Create(ctx, sess, uuid.New(), userID, n, s.d.Now())
		return err
	})
	return p, err
}

// Get is get; ErrProjectNotFound when the workspace has no such project.
func (s *Service) Get(ctx context.Context, ws scope.Workspace, id uuid.UUID) (domain.Project, error) {
	var out domain.Project
	err := s.read(ctx, ws, func(sess db.Session) error {
		p, ok, err := s.d.Store.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrProjectNotFound
		}
		ps := []domain.Project{p}
		if err := s.withLinks(ctx, sess, ps); err != nil {
			return err
		}
		out = ps[0]
		return nil
	})
	return out, err
}

// List is list: a page of the workspace's projects in no set order.
func (s *Service) List(ctx context.Context, ws scope.Workspace, limit, offset int32) ([]domain.Project, error) {
	var out []domain.Project
	err := s.read(ctx, ws, func(sess db.Session) error {
		ps, err := s.d.Store.List(ctx, sess, limit, offset)
		if err != nil {
			return err
		}
		if err := s.withLinks(ctx, sess, ps); err != nil {
			return err
		}
		out = ps
		return nil
	})
	return out, err
}

// withLinks fills each project's children the workspace can see
// (repository.py _scoped_links).
func (s *Service) withLinks(ctx context.Context, sess db.Session, ps []domain.Project) error {
	ids := make([]uuid.UUID, len(ps))
	for i, p := range ps {
		ids[i] = uuid.MustParse(p.ID)
	}
	links, err := s.d.Store.Links(ctx, sess, ids)
	if err != nil {
		return err
	}
	var skills, mcps, agents []string
	for _, l := range links {
		skills = append(skills, l.Skills...)
		mcps = append(mcps, l.MCPInstances...)
		agents = append(agents, l.Agents...)
	}
	ws := sess.Workspace()
	skillNames, err := s.d.Agents.SkillNames(ctx, ws, skills)
	if err != nil {
		return err
	}
	mcpNames, err := s.d.Connections.MCPInstanceNames(ctx, ws, mcps)
	if err != nil {
		return err
	}
	agentNames, err := s.d.Agents.AgentNames(ctx, ws, agents)
	if err != nil {
		return err
	}
	for i := range ps {
		l := links[ps[i].ID]
		ps[i].Skills = refs(l.Skills, skillNames)
		ps[i].MCPInstances = refs(l.MCPInstances, mcpNames)
		ps[i].Agents = refs(l.Agents, agentNames)
	}
	return nil
}

func refs(ids []string, names map[string]string) []domain.Ref {
	out := []domain.Ref{}
	for _, id := range ids {
		if name, ok := names[id]; ok {
			out = append(out, domain.Ref{ID: id, Name: name})
		}
	}
	return out
}

// Update is update_project: parent checks first, then the write, so a
// foreign project with a bad parent answers the parent's error.
func (s *Service) Update(ctx context.Context, ws scope.Workspace, id uuid.UUID, p domain.Patch) (domain.Project, error) {
	if p.ParentProjectID.Set && p.ParentProjectID.Value != nil {
		err := s.read(ctx, ws, func(sess db.Session) error {
			parent, err := s.inWorkspace(ctx, sess, *p.ParentProjectID.Value, "Parent project")
			if err != nil {
				return err
			}
			cycle, err := s.isAncestorOrSelf(ctx, sess, id, parent)
			if err != nil {
				return err
			}
			if cycle {
				return domain.ErrCycle
			}
			canonical := parent.String()
			p.ParentProjectID.Value = &canonical
			return nil
		})
		if err != nil {
			return domain.Project{}, err
		}
	}
	var found bool
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		var err error
		found, err = s.d.Store.Update(ctx, sess, id, p, s.d.Now())
		return err
	})
	if err != nil {
		return domain.Project{}, err
	}
	if !found {
		return domain.Project{}, domain.ErrProjectNotFound
	}
	return s.Get(ctx, ws, id)
}

// isAncestorOrSelf is _is_ancestor_or_self: walks up from parent, one
// workspace-filtered read per level, no depth limit, stopping at a missing
// node or a repeat.
func (s *Service) isAncestorOrSelf(ctx context.Context, sess db.Session, project, parent uuid.UUID) (bool, error) {
	current := &parent
	seen := map[uuid.UUID]bool{}
	for current != nil && !seen[*current] {
		if *current == project {
			return true, nil
		}
		seen[*current] = true
		n, ok, err := s.d.Store.Node(ctx, sess, *current)
		if err != nil || !ok {
			return false, err
		}
		if n.ParentProjectID == nil {
			return false, nil
		}
		next, err := uuid.Parse(*n.ParentProjectID)
		if err != nil {
			return false, err
		}
		current = &next
	}
	return false, nil
}

// Delete is delete; ErrProjectNotFound when there was none.
func (s *Service) Delete(ctx context.Context, ws scope.Workspace, id uuid.UUID) error {
	var found bool
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		var err error
		found, err = s.d.Store.Delete(ctx, sess, id)
		return err
	})
	if err != nil {
		return err
	}
	if !found {
		return domain.ErrProjectNotFound
	}
	return nil
}

func (s *Service) childExists(ctx context.Context, ws scope.Workspace, k domain.LinkKind, id string) (bool, error) {
	switch k {
	case domain.LinkSkill:
		return s.d.Agents.SkillExists(ctx, ws, id)
	case domain.LinkMCPInstance:
		return s.d.Connections.MCPInstanceExists(ctx, ws, id)
	case domain.LinkAgent:
	}
	return s.d.Agents.AgentExists(ctx, ws, id)
}

// Link is add_skill, add_mcp_instance and add_agent: the project, then the
// child, each resolved in the workspace (404 NotFoundError otherwise), then
// an idempotent insert.
func (s *Service) Link(ctx context.Context, ws scope.Workspace, k domain.LinkKind, project uuid.UUID, child string) error {
	err := s.read(ctx, ws, func(sess db.Session) error {
		_, err := s.inWorkspace(ctx, sess, project.String(), "Project")
		return err
	})
	if err != nil {
		return err
	}
	childID, err := uuid.Parse(child)
	if err != nil {
		return &domain.NotFoundError{Label: k.Label()}
	}
	ok, err := s.childExists(ctx, ws, k, childID.String())
	if err != nil {
		return err
	}
	if !ok {
		return &domain.NotFoundError{Label: k.Label()}
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return s.d.Store.Link(ctx, sess, k, project, childID)
	})
}

// Unlink is remove_*: only the project is resolved; removing a link that
// does not exist is a no-op.
func (s *Service) Unlink(ctx context.Context, ws scope.Workspace, k domain.LinkKind, project, child uuid.UUID) error {
	err := s.read(ctx, ws, func(sess db.Session) error {
		_, err := s.inWorkspace(ctx, sess, project.String(), "Project")
		return err
	})
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return s.d.Store.Unlink(ctx, sess, k, project, child)
	})
}
