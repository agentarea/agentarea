package service

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

func ptr[T any](v T) *T { return &v }

// Create is create_agent, the route's trigger refusal and the owner grant.
func (s *Service) Create(ctx context.Context, c authn.Caller, in Create) (View, error) {
	ws := c.Workspace
	tools := in.Tools
	if err := s.validateCodeNames(tools); err != nil {
		return View{}, err
	}
	if len(in.Triggers) > 0 {
		if s.d.Triggers == nil {
			return View{}, &UnwiredError{Feature: "creating triggers with an agent"}
		}
		if err := s.d.Triggers.Check(ctx, c, in.Triggers); err != nil {
			return View{}, err
		}
	}
	if err := s.bindMCP(ctx, c, tools, true); err != nil {
		return View{}, err
	}
	targets, tools := liftApprovals(tools)
	if err := s.validateToolModels(ctx, ws, tools); err != nil {
		return View{}, err
	}
	if err := s.validateDelegates(ctx, ws, tools, nil); err != nil {
		return View{}, err
	}
	if err := s.requireUsable(ctx, c, tools, nil); err != nil {
		return View{}, err
	}
	modelID, err := s.validateModelID(ctx, ws, in.ModelID)
	if err != nil {
		return View{}, err
	}
	clientID, err := s.validateClientID(ctx, ws, c, in.ClientID)
	if err != nil {
		return View{}, err
	}
	var skillIDs []uuid.UUID
	if err := s.read(ctx, ws, func(sess db.Session) error {
		var err error
		skillIDs, err = s.skillsExist(ctx, sess, in.SkillIDs)
		return err
	}); err != nil {
		return View{}, err
	}
	raw, err := StoredJSON(tools)
	if err != nil {
		return View{}, err
	}
	a := domain.Agent{
		ID: uuid.NewString(), Name: in.Name, Status: domain.StatusActive, Description: &in.Description,
		Instruction: &in.Instruction, ModelID: modelID, ClientID: clientID, Tools: raw, Planning: in.Planning,
		A2UIEnabled: in.A2UIEnabled, ReasoningEffort: in.ReasoningEffort, ReasoningMaxTokens: in.ReasoningMaxTokens,
		AnswerCheck: in.AnswerCheck, AgentType: in.AgentType,
	}
	now := s.d.Now()
	err = retrySlug(func() error {
		return s.write(ctx, ws, func(sess db.Session) error {
			if err := s.insertAgent(ctx, sess, c, &a, skillIDs, now); err != nil {
				return err
			}
			if err := s.syncLoans(ctx, a.ID, tools, nil); err != nil {
				return err
			}
			return s.syncApprovals(ctx, sess, c, a.ID, targets, false)
		})
	})
	if err != nil {
		return View{}, err
	}
	if len(in.Triggers) > 0 {
		if err := s.d.Triggers.Create(ctx, c, a.ID, in.Triggers); err != nil {
			if uerr := s.unmake(context.WithoutCancel(ctx), c, a.ID, tools); uerr != nil {
				return View{}, errors.Join(err, uerr)
			}
			return View{}, err
		}
	}
	a.CreatedBy, a.WorkspaceID = c.UserID, ws.ID()
	views, err := s.views(ctx, ws, []domain.Agent{a})
	return views[0], err
}

// insertAgent picks the slug and writes the row, its grants and skills.
func (s *Service) insertAgent(ctx context.Context, sess db.Session, c authn.Caller, a *domain.Agent, skillIDs []uuid.UUID, now time.Time) error {
	ws := c.Workspace
	slug, err := s.resolveSlug(ctx, sess, a.Name)
	if err != nil {
		return err
	}
	a.Slug = slug
	if err := s.store.Insert(ctx, sess, c.UserID, *a, now); err != nil {
		return err
	}
	if err := s.grantOwner(ctx, c, a.ID); err != nil {
		return err
	}
	if err := authz.EnrollAgent(ctx, s.d.Graph, a.ID, ws.ID()); err != nil {
		return err
	}
	if len(skillIDs) > 0 {
		if err := s.store.SetSkills(ctx, sess, uuid.MustParse(a.ID), skillIDs, now); err != nil {
			return err
		}
	}
	s.audit(ctx, sess, c, "agent.create", "agent", a.ID)
	return nil
}

func (s *Service) grantOwner(ctx context.Context, c authn.Caller, id string) error {
	return authz.GrantResourceOwner(ctx, s.d.Graph, id, c.Workspace.ID(), authz.UserSubject(c.UserID), authz.AgentOwnerRelations())
}

func (s *Service) requireUsable(ctx context.Context, c authn.Caller, tools, previous []domain.Tool) error {
	prev := connectionIDs(previous)
	for _, id := range sortedKeys(connectionIDs(tools)) {
		if prev[id] {
			continue
		}
		ok, err := s.d.Graph.Check(ctx, c.GraphSubject(), authz.CanUseConnection, authz.TypeResource, id)
		if err != nil {
			return err
		}
		if !ok {
			return &PermissionError{Msg: "Connection " + id + " is someone else's personal connection; its owner can share it with the workspace or attach it themselves."}
		}
	}
	return nil
}

// PermissionError is Python's builtin PermissionError: a 403 permission_denied.
type PermissionError struct{ Msg string }

func (e *PermissionError) Error() string { return e.Msg }

// views reads each agent's overlays: approval flags, client, A2A address.
func (s *Service) views(ctx context.Context, ws scope.Workspace, agents []domain.Agent) ([]View, error) {
	ids := make([]string, len(agents))
	for i, a := range agents {
		ids[i] = a.ID
	}
	var targets map[string][]string
	if s.d.Approvals != nil {
		var err error
		if targets, err = s.d.Approvals.Targets(ctx, ws, ids); err != nil {
			return nil, err
		}
	}
	var clientIDs []uuid.UUID
	for _, a := range agents {
		if a.ClientID != nil {
			clientIDs = append(clientIDs, uuid.MustParse(*a.ClientID))
		}
	}
	var clients map[string]storeClient
	if len(clientIDs) > 0 {
		if err := s.read(ctx, ws, func(sess db.Session) error {
			var err error
			clients, err = s.clients(ctx, sess, clientIDs)
			return err
		}); err != nil {
			return nil, err
		}
	}
	online := map[string]bool{}
	if s.d.Presence != nil {
		var runnerIDs []string
		for id, cl := range clients {
			if domain.RunnerKind(cl.Kind) {
				runnerIDs = append(runnerIDs, id)
			}
		}
		if len(runnerIDs) > 0 {
			var err error
			if online, err = s.d.Presence.Online(ctx, runnerIDs); err != nil {
				return nil, err
			}
		}
	}
	out := make([]View, len(agents))
	for i, a := range agents {
		v := View{Agent: a, Tools: toolsFromColumn(a.Tools)}
		if t := targets[a.ID]; len(t) > 0 && len(v.Tools) > 0 {
			v.Tools = applyTargets(v.Tools, t)
		}
		if a.ClientID != nil {
			if cl, ok := clients[*a.ClientID]; ok {
				cl := cl
				v.Client, v.Online = &cl, online[cl.ID]
			}
		}
		if !a.IsCatalog && s.d.A2AAgentURL != "" {
			v.A2AURL = ptr(strings.Replace(strings.TrimRight(s.d.A2AAgentURL, "/"), "{agent_id}", a.ID, 1))
		}
		out[i] = v
	}
	return out, nil
}

func applyTargets(tools []domain.Tool, targets []string) []domain.Tool {
	has := map[string]bool{}
	for _, t := range targets {
		has[t] = true
	}
	out := make([]domain.Tool, len(tools))
	for i, t := range tools {
		st := domain.Settings{}
		if t.Settings != nil {
			st = *t.Settings
		}
		if t.Type == domain.ToolMCP {
			if t.Settings == nil {
				out[i] = t
				continue
			}
			if st.MCPAllowed != nil {
				perms := make([]domain.MCPPermission, len(*st.MCPAllowed))
				for j, p := range *st.MCPAllowed {
					ticked := has["tool:mcp:"+t.Name+":"+p.ToolName] || has["tool:"+p.ToolName]
					perms[j] = domain.MCPPermission{ToolName: p.ToolName, RequiresUserConfirmation: &ticked}
				}
				st.MCPAllowed = &perms
			}
		} else if t.Name != "" {
			st.RequiresUserConfirmation = ptr(has["tool:"+t.Name[strings.LastIndex(t.Name, "/")+1:]])
		}
		t.Settings = &st
		out[i] = t
	}
	return out
}

// List is list_agents: the agents the graph says the caller may read.
func (s *Service) List(ctx context.Context, c authn.Caller) ([]View, error) {
	var all []domain.Agent
	if err := s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		all, err = s.store.List(ctx, sess)
		return err
	}); err != nil {
		return nil, err
	}
	readable, err := authz.ReadableResourceIDs(ctx, s.d.Graph, c.GraphSubject())
	if err != nil {
		return nil, err
	}
	var shown []domain.Agent
	for _, a := range all {
		if _, ok := readable[a.ID]; ok && a.Status != domain.StatusArchived && a.HarnessClientID == nil {
			shown = append(shown, a)
		}
	}
	return s.views(ctx, c.Workspace, shown)
}

func (s *Service) load(ctx context.Context, ws scope.Workspace, id uuid.UUID, withSkills bool) (domain.Agent, bool, error) {
	var a domain.Agent
	var ok bool
	err := s.read(ctx, ws, func(sess db.Session) error {
		var err error
		a, ok, err = s.store.Get(ctx, sess, id)
		if err != nil || !ok || !withSkills {
			return err
		}
		a.Skills, err = s.store.Skills(ctx, sess, id)
		return err
	})
	return a, ok, err
}

// Get is get_agent: resolution, then the PDP read check.
func (s *Service) Get(ctx context.Context, c authn.Caller, identifier string) (View, error) {
	id, found, err := s.Resolve(ctx, c.Workspace, identifier)
	if err != nil {
		return View{}, err
	}
	if !found {
		return View{}, domain.ErrAgentNotFound
	}
	a, ok, err := s.load(ctx, c.Workspace, id, true)
	if err != nil {
		return View{}, err
	}
	if !ok {
		return View{}, domain.ErrAgentNotFound
	}
	if err := s.Require(ctx, c, "read", id); err != nil {
		return View{}, err
	}
	v, err := s.views(ctx, c.Workspace, []domain.Agent{a})
	return v[0], err
}

func (s *Service) resolveNeeding(ctx context.Context, c authn.Caller, identifier, permission string) (uuid.UUID, error) {
	id, found, err := s.Resolve(ctx, c.Workspace, identifier)
	if err != nil {
		return uuid.Nil, err
	}
	if !found {
		return uuid.Nil, domain.ErrAgentNotFound
	}
	return id, s.Require(ctx, c, permission, id)
}

// Update is update_agent after its route's edit check.
func (s *Service) Update(ctx context.Context, c authn.Caller, identifier string, p Patch) (View, error) {
	ws := c.Workspace
	id, err := s.resolveNeeding(ctx, c, identifier, "edit")
	if err != nil {
		return View{}, err
	}
	if p.Tools != nil {
		if err := s.validateCodeNames(*p.Tools); err != nil {
			return View{}, err
		}
	}
	var skillIDs []uuid.UUID
	if p.SkillIDs != nil {
		if err := s.read(ctx, ws, func(sess db.Session) error {
			var err error
			skillIDs, err = s.skillsExist(ctx, sess, *p.SkillIDs)
			return err
		}); err != nil {
			return View{}, err
		}
	}
	a, ok, err := s.load(ctx, ws, id, false)
	if err != nil {
		return View{}, err
	}
	if !ok {
		return View{}, domain.ErrAgentNotFound
	}
	if a.Status == domain.StatusArchived {
		return View{}, &domain.ErrAgentArchivedError{ID: a.ID}
	}
	if p.ReasoningEffort.Set || p.ReasoningMaxTokens.Set {
		effort, tokens := a.ReasoningEffort, a.ReasoningMaxTokens
		if p.ReasoningEffort.Set {
			effort = p.ReasoningEffort.Value
		}
		if p.ReasoningMaxTokens.Set {
			tokens = p.ReasoningMaxTokens.Value
		}
		if truthy(effort) && tokens != nil && *tokens != 0 {
			return View{}, domain.ErrReasoningConflict
		}
	}
	previous := toolsFromColumn(a.Tools)
	var targets []string
	var edited []domain.Tool
	if p.Tools != nil {
		edited = *p.Tools
		if err := s.bindMCP(ctx, c, edited, true); err != nil {
			return View{}, err
		}
		if err := s.validateToolModels(ctx, ws, edited); err != nil {
			return View{}, err
		}
		if err := s.validateDelegates(ctx, ws, edited, previous); err != nil {
			return View{}, err
		}
		if err := s.requireUsable(ctx, c, edited, previous); err != nil {
			return View{}, err
		}
	}
	if p.Name != nil {
		a.Name = *p.Name
	}
	if p.Description.Set {
		a.Description = p.Description.Value
	}
	if p.Instruction.Set {
		a.Instruction = p.Instruction.Value
	}
	if p.ModelID.Set {
		if a.ModelID, err = s.validateModelID(ctx, ws, p.ModelID.Value); err != nil {
			return View{}, err
		}
	}
	if p.ClientID.Set {
		if a.ClientID, err = s.validateClientID(ctx, ws, c, p.ClientID.Value); err != nil {
			return View{}, err
		}
	}
	var stored []domain.Tool
	if p.Tools != nil {
		targets, stored = liftApprovals(edited)
		if a.Tools, err = StoredJSON(stored); err != nil {
			return View{}, err
		}
	}
	if p.Planning.Set {
		a.Planning = p.Planning.Value
	}
	if p.A2UIEnabled.Set {
		a.A2UIEnabled = p.A2UIEnabled.Value
	}
	if p.ReasoningEffort.Set {
		a.ReasoningEffort = p.ReasoningEffort.Value
	}
	if p.ReasoningMaxTokens.Set {
		a.ReasoningMaxTokens = p.ReasoningMaxTokens.Value
	}
	if p.AnswerCheck.Set {
		a.AnswerCheck = nil
		if p.AnswerCheck.Value != nil {
			a.AnswerCheck = *p.AnswerCheck.Value
		}
	}
	if p.AgentType != nil {
		a.AgentType = *p.AgentType
	}
	now := s.d.Now()
	if err := s.write(ctx, ws, func(sess db.Session) error {
		if p.Tools != nil && s.d.Approvals != nil {
			if err := s.d.Approvals.Release(ctx, sess, c, a.ID, untickedTargets(edited)); err != nil {
				return err
			}
		}
		if err := s.store.Update(ctx, sess, a, now); err != nil {
			return err
		}
		s.audit(ctx, sess, c, "agent.update", "agent", a.ID)
		if p.Tools == nil {
			return nil
		}
		if err := s.syncApprovals(ctx, sess, c, a.ID, targets, true); err != nil {
			return err
		}
		return s.syncLoans(ctx, a.ID, stored, previous)
	}); err != nil {
		return View{}, err
	}
	if p.SkillIDs != nil {
		if err := s.write(ctx, ws, func(sess db.Session) error { return s.store.SetSkills(ctx, sess, id, skillIDs, now) }); err != nil {
			return View{}, err
		}
	}
	return s.afterWrite(ctx, c, id)
}

func truthy(s *string) bool { return s != nil && *s != "" }

func (s *Service) afterWrite(ctx context.Context, c authn.Caller, id uuid.UUID) (View, error) {
	a, ok, err := s.load(ctx, c.Workspace, id, true)
	if err != nil {
		return View{}, err
	}
	if !ok {
		return View{}, domain.ErrAgentNotFound
	}
	if a.CreatedBy == c.UserID {
		if err := s.grantOwner(ctx, c, a.ID); err != nil {
			return View{}, err
		}
	}
	v, err := s.views(ctx, c.Workspace, []domain.Agent{a})
	return v[0], err
}

// setStatus moves the agent from one status to another; the audit row
// (action) is written whether or not the status moved, as @audited does.
func (s *Service) setStatus(ctx context.Context, c authn.Caller, id uuid.UUID, from, to, action string) error {
	a, ok, err := s.load(ctx, c.Workspace, id, false)
	if err != nil {
		return err
	}
	if !ok {
		return domain.ErrAgentNotFound
	}
	return s.write(ctx, c.Workspace, func(sess db.Session) error {
		if a.Status == from {
			a.Status = to
			if err := s.store.Update(ctx, sess, a, s.d.Now()); err != nil {
				return err
			}
		}
		s.audit(ctx, sess, c, action, "agent", a.ID)
		return nil
	})
}

// Archive is archive_agent after the delete check; idempotent.
func (s *Service) Archive(ctx context.Context, c authn.Caller, identifier string) error {
	id, err := s.resolveNeeding(ctx, c, identifier, "delete")
	if err != nil {
		return err
	}
	return s.setStatus(ctx, c, id, domain.StatusActive, domain.StatusArchived, "agent.archive")
}

// Restore is restore_agent after the delete check; it answers the agent with its skills.
func (s *Service) Restore(ctx context.Context, c authn.Caller, identifier string) (View, error) {
	id, err := s.resolveNeeding(ctx, c, identifier, "delete")
	if err != nil {
		return View{}, err
	}
	if err := s.setStatus(ctx, c, id, domain.StatusArchived, domain.StatusActive, "agent.restore"); err != nil {
		return View{}, err
	}
	a, ok, err := s.load(ctx, c.Workspace, id, true)
	if err != nil {
		return View{}, err
	}
	if !ok {
		return View{}, domain.ErrAgentNotFound
	}
	v, err := s.views(ctx, c.Workspace, []domain.Agent{a})
	return v[0], err
}

// unmake is delete_agent rolling back a create whose triggers failed: the row,
// and what the create wrote beside it (loans, approval rules, graph tuples),
// and the agent's wallet keys.
func (s *Service) unmake(ctx context.Context, c authn.Caller, id string, tools []domain.Tool) error {
	err := s.write(ctx, c.Workspace, func(sess db.Session) error {
		if _, err := s.store.Delete(ctx, sess, uuid.MustParse(id)); err != nil {
			return err
		}
		if s.d.Wallets != nil {
			if err := s.d.Wallets.DeleteCredentials(ctx, sess, c.UserID, id); err != nil {
				return err
			}
		}
		if err := s.syncLoans(ctx, id, nil, tools); err != nil {
			return err
		}
		if s.d.Approvals == nil {
			return nil
		}
		return s.d.Approvals.Sync(ctx, sess, c, id, nil)
	})
	if err != nil {
		return err
	}
	if rw, ok := s.d.Graph.(authz.ReadWriter); ok {
		return authz.RevokeResource(ctx, rw, id)
	}
	return nil
}
