package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

// Service is AgentService and the agent routes' orchestration.
type Service struct {
	d     Deps
	store agentStore
}

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	return &Service{d: d, store: store.Agents{}}
}

// Set is a nullable field of a partial update: Set when the key was sent.
type Set[T any] struct {
	Set   bool
	Value *T
}

// Create is AgentCreate after validation.
type Create struct {
	Name               string
	Description        string
	Instruction        string
	ModelID            *string
	ClientID           *string
	Tools              []domain.Tool
	Planning           *bool
	A2UIEnabled        *bool
	ReasoningEffort    *string
	ReasoningMaxTokens *int32
	AnswerCheck        []byte
	SkillIDs           []string
	AgentType          string
	// Triggers are the TriggerSpec documents sent with the agent.
	Triggers []json.RawMessage
}

// Patch is AgentUpdate's exclude_unset dump.
type Patch struct {
	Name               *string
	Description        Set[string]
	Instruction        Set[string]
	ModelID            Set[string]
	ClientID           Set[string]
	Tools              *[]domain.Tool
	Planning           Set[bool]
	A2UIEnabled        Set[bool]
	ReasoningEffort    Set[string]
	ReasoningMaxTokens Set[int32]
	AnswerCheck        Set[[]byte]
	SkillIDs           *[]string
	AgentType          *string
}

// View is an agent with what a response overlays: tools with approval
// flags, the runner client, the A2A address.
type View struct {
	Agent  domain.Agent
	Tools  []domain.Tool
	Client *store.ClientSummary
	Online bool
	A2AURL *string
}

func (s *Service) read(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

func (s *Service) write(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error { return fn(sess) })
}

// Resolve is _resolve_agent_id: a UUID as is, else a workspace slug.
func (s *Service) Resolve(ctx context.Context, ws scope.Workspace, identifier string) (uuid.UUID, bool, error) {
	if u, err := uuid.Parse(identifier); err == nil {
		return u, true, nil
	}
	var out uuid.UUID
	var found bool
	err := s.read(ctx, ws, func(sess db.Session) error {
		a, ok, err := s.store.BySlug(ctx, sess, identifier)
		if ok {
			out, found = uuid.MustParse(a.ID), true
		}
		return err
	})
	return out, found, err
}

// Require is require_permission against the agent, as a 403 "Permission denied".
func (s *Service) Require(ctx context.Context, c authn.Caller, permission string, id uuid.UUID) error {
	relation, ok := authz.RelationForPermission(permission)
	if !ok {
		return ErrDenied
	}
	allowed, err := s.d.Graph.Check(ctx, c.GraphSubject(), relation, authz.TypeResource, id.String())
	if err != nil {
		return err
	}
	if !allowed {
		return ErrDenied
	}
	return nil
}

// ErrDenied is a refused permission check.
var ErrDenied = authz.ErrDenied

func isUUID(v string) bool { _, err := uuid.Parse(v); return err == nil }

func toolsFromColumn(raw []byte) []domain.Tool {
	tools, _ := ParseStoredTools(raw)
	return tools
}

func mcpNamed(tools []domain.Tool) bool {
	for _, t := range tools {
		if t.Type == domain.ToolMCP && t.Name != "" && !isUUID(t.Name) {
			return true
		}
	}
	return false
}

func (s *Service) bindMCP(ctx context.Context, c authn.Caller, tools []domain.Tool, refuseUnbound bool) error {
	if !mcpNamed(tools) {
		return nil
	}
	if s.d.Connections == nil {
		return &UnwiredError{Feature: "binding an MCP tool by connection name"}
	}
	for i, t := range tools {
		if t.Type != domain.ToolMCP || t.Name == "" || isUUID(t.Name) {
			continue
		}
		id, err := s.d.Connections.BindMCPName(ctx, c, t.Name, refuseUnbound)
		if err != nil {
			return err
		}
		if id != "" {
			tools[i].Name = id
		}
	}
	return nil
}

// liftApprovals is _lift_approval_toggles: the targets of ticked tools, and
// the tools with every confirmation flag removed.
func liftApprovals(tools []domain.Tool) ([]string, []domain.Tool) {
	set := map[string]bool{}
	out := make([]domain.Tool, len(tools))
	for i, t := range tools {
		out[i] = t
		if t.Settings == nil {
			continue
		}
		st := *t.Settings
		if t.Type == domain.ToolMCP {
			if st.MCPAllowed != nil {
				perms := make([]domain.MCPPermission, len(*st.MCPAllowed))
				for j, p := range *st.MCPAllowed {
					if p.RequiresUserConfirmation != nil && *p.RequiresUserConfirmation && p.ToolName != "" && t.Name != "" {
						set["tool:mcp:"+t.Name+":"+p.ToolName] = true
					}
					perms[j] = domain.MCPPermission{ToolName: p.ToolName}
				}
				st.MCPAllowed = &perms
			}
		} else if st.RequiresUserConfirmation != nil && *st.RequiresUserConfirmation && t.Name != "" {
			set["tool:"+t.Name[strings.LastIndex(t.Name, "/")+1:]] = true
		}
		st.RequiresUserConfirmation = nil
		out[i].Settings = &st
	}
	targets := make([]string, 0, len(set))
	for k := range set {
		targets = append(targets, k)
	}
	slices.Sort(targets)
	return targets, out
}

func (s *Service) syncApprovals(ctx context.Context, sess db.Session, c authn.Caller, id string, targets []string, mustRun bool) error {
	if s.d.Approvals == nil {
		if len(targets) > 0 {
			return &UnwiredError{Feature: "tool approval rules"}
		}
		return nil
	}
	if len(targets) == 0 && !mustRun {
		return nil
	}
	return s.d.Approvals.Sync(ctx, sess, c, id, targets)
}

func connectionIDs(tools []domain.Tool) map[string]bool {
	out := map[string]bool{}
	for _, t := range tools {
		switch t.Type {
		case domain.ToolMCP:
			if isUUID(t.Name) {
				out[uuid.MustParse(t.Name).String()] = true
			}
		case domain.ToolOpenAPI:
			if t.Settings != nil && t.Settings.OpenAPIConnectionID != nil && isUUID(*t.Settings.OpenAPIConnectionID) {
				out[uuid.MustParse(*t.Settings.OpenAPIConnectionID).String()] = true
			}
		}
	}
	return out
}

func (s *Service) syncLoans(ctx context.Context, agentID string, tools, previous []domain.Tool) error {
	attached, detached := connectionIDs(tools), connectionIDs(previous)
	if len(attached) == 0 && len(detached) == 0 {
		return nil
	}
	if s.d.Connections == nil {
		return &UnwiredError{Feature: "lending connections to an agent"}
	}
	for _, id := range sortedKeys(attached) {
		if !detached[id] {
			if err := s.d.Connections.Lend(ctx, id, agentID); err != nil {
				return err
			}
		}
	}
	for _, id := range sortedKeys(detached) {
		if !attached[id] {
			if err := s.d.Connections.Withdraw(ctx, id, agentID); err != nil {
				return err
			}
		}
	}
	return nil
}

func sortedKeys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	slices.Sort(out)
	return out
}

// toolModelSettings are the model settings each code toolset takes.
func toolModelSettings(tool string) []string {
	if tool == "agentarea/media" {
		return []string{"image_model_id", "video_model_id"}
	}
	return nil
}

func (s *Service) modelKind(ctx context.Context, ws scope.Workspace, id, setting string) (string, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return "", &domain.InvalidError{Code: domain.CodeInvalidModelID, Detail: fmt.Sprintf(
			"Invalid %s '%s': expected the UUID of a model instance. List available instances via GET /v1/model-instances.", setting, id)}
	}
	if s.d.Models == nil {
		return "", &UnwiredError{Feature: "model instance validation"}
	}
	kind, found, err := s.d.Models.ModelKind(ctx, ws, u.String())
	if err != nil {
		return "", err
	}
	if !found {
		return "", &domain.InvalidError{Code: domain.CodeInvalidModelID, Detail: fmt.Sprintf(
			"Model instance '%s' does not exist in this workspace. Create one via POST /v1/model-instances.", id)}
	}
	return kind, nil
}

func (s *Service) validateModelID(ctx context.Context, ws scope.Workspace, id *string) (*string, error) {
	if id == nil || strings.TrimSpace(*id) == "" {
		return nil, nil
	}
	kind, err := s.modelKind(ctx, ws, *id, "model_id")
	if err != nil {
		return nil, err
	}
	if kind != "chat" {
		return nil, &domain.InvalidError{Code: domain.CodeInvalidModelID, Detail: fmt.Sprintf(
			"Model instance '%s' is a %s model; an agent's main model must be a chat model.", *id, kind)}
	}
	return id, nil
}

func (s *Service) validateToolModels(ctx context.Context, ws scope.Workspace, tools []domain.Tool) error {
	kinds := map[string]string{"image_model_id": "image", "video_model_id": "video"}
	for _, t := range tools {
		if t.Type != domain.ToolCode {
			continue
		}
		given := map[string]*string{}
		if t.Settings != nil {
			given["image_model_id"], given["video_model_id"] = t.Settings.ImageModelID, t.Settings.VideoModelID
		}
		allowed := toolModelSettings(t.Name)
		for _, setting := range []string{"image_model_id", "video_model_id"} {
			v := given[setting]
			if v == nil {
				continue
			}
			if !slices.Contains(allowed, setting) {
				return &domain.InvalidError{Code: domain.CodeInvalidModelID, Detail: fmt.Sprintf(
					"Tool '%s' takes no %s.", t.Name, setting)}
			}
			kind, err := s.modelKind(ctx, ws, *v, setting)
			if err != nil {
				return err
			}
			if kind != kinds[setting] {
				return &domain.InvalidError{Code: domain.CodeInvalidModelID, Detail: fmt.Sprintf(
					"Model instance '%s' is a %s model; %s of '%s' must be a %s model.", *v, kind, setting, t.Name, kinds[setting])}
			}
		}
		if allowed != nil && given["image_model_id"] == nil && given["video_model_id"] == nil {
			return &domain.InvalidError{Code: domain.CodeInvalidModelID, Detail: fmt.Sprintf(
				"Tool '%s' needs an image_model_id or a video_model_id.", t.Name)}
		}
	}
	return nil
}

func (s *Service) validateClientID(ctx context.Context, ws scope.Workspace, c authn.Caller, id *string) (*string, error) {
	if id == nil {
		return nil, nil
	}
	u, err := uuid.Parse(*id)
	bad := &domain.InvalidError{Code: domain.CodeInvalidClientID, Detail: fmt.Sprintf(
		"Client '%s' is no Codex or Claude Code client of this workspace", *id)}
	if err != nil {
		return nil, bad
	}
	var kind string
	var found bool
	err = s.read(ctx, ws, func(sess db.Session) error {
		m, err := s.store.Clients(ctx, sess, []uuid.UUID{u})
		if err != nil {
			return err
		}
		cl, ok := m[u.String()]
		kind, found = cl.Kind, ok
		return nil
	})
	if err != nil {
		return nil, err
	}
	if !found || !domain.RunnerKind(kind) {
		return nil, bad
	}
	if err := s.Require(ctx, c, "use", u); err != nil {
		if errors.Is(err, ErrDenied) {
			return nil, bad
		}
		return nil, err
	}
	canon := u.String()
	return &canon, nil
}

func (s *Service) delegateAgentID(ctx context.Context, ws scope.Workspace, name string, id *string) (string, error) {
	var agents []domain.Agent
	if err := s.read(ctx, ws, func(sess db.Session) error {
		var err error
		agents, err = s.store.List(ctx, sess)
		return err
	}); err != nil {
		return "", err
	}
	if id != nil && *id != "" {
		for _, a := range agents {
			if u, err := uuid.Parse(*id); err == nil && a.ID == u.String() && a.Status != domain.StatusArchived {
				return a.ID, nil
			}
		}
		return "", &domain.InvalidError{Code: domain.CodeInvalidDelegate, Detail: fmt.Sprintf("Delegate '%s': no agent %s in this workspace.", name, *id)}
	}
	var matches []domain.Agent
	for _, a := range agents {
		if a.Name == name && a.Status != domain.StatusArchived && a.HarnessClientID == nil {
			matches = append(matches, a)
		}
	}
	switch len(matches) {
	case 0:
		return "", &domain.InvalidError{Code: domain.CodeInvalidDelegate, Detail: fmt.Sprintf("No agent named '%s' in this workspace.", name)}
	case 1:
		return matches[0].ID, nil
	}
	return "", &domain.InvalidError{Code: domain.CodeInvalidDelegate, Detail: fmt.Sprintf(
		"%d agents here are named '%s'; pass the one to delegate to as settings.agent_id.", len(matches), name)}
}

type binding struct{ name, url, secret string }

func credentialBindings(tools []domain.Tool) map[binding]bool {
	out := map[binding]bool{}
	for _, t := range tools {
		if t.Type == domain.ToolAgent && t.Settings != nil && t.Settings.AuthSecretName != nil && *t.Settings.AuthSecretName != "" {
			url := "None"
			if t.Settings.A2AURL != nil {
				url = *t.Settings.A2AURL
			}
			out[binding{t.Name, url, *t.Settings.AuthSecretName}] = true
		}
	}
	return out
}

func (s *Service) validateDelegates(ctx context.Context, ws scope.Workspace, tools, previous []domain.Tool) error {
	seen := map[string]string{}
	for i, t := range tools {
		if t.Type != domain.ToolAgent {
			continue
		}
		tn := domain.DelegateToolName(t.Name)
		if other, dup := seen[tn]; dup {
			return &domain.InvalidError{Code: domain.CodeInvalidDelegate, Detail: fmt.Sprintf(
				"Delegates '%s' and '%s' both become the tool '%s'; rename one.", other, t.Name, tn)}
		}
		seen[tn] = t.Name
		st := domain.Settings{}
		if t.Settings != nil {
			st = *t.Settings
		}
		switch {
		case st.A2AURL != nil && st.AgentID != nil && *st.AgentID != "":
			return &domain.InvalidError{Code: domain.CodeInvalidDelegate, Detail: fmt.Sprintf(
				"Delegate '%s': agent_id names a workspace agent, and a remote delegate is reached at its a2a_url; give one of them.", t.Name)}
		case st.A2AURL != nil:
			u := domain.AgentAddress(*st.A2AURL)
			st.A2AURL = &u
			if !validHTTPURL(u) {
				return &domain.InvalidError{Code: domain.CodeInvalidDelegate, Detail: fmt.Sprintf(
					"Delegate '%s': a2a_url must be an http(s) URL with a host.", t.Name)}
			}
		case st.AuthSecretName != nil && *st.AuthSecretName != "":
			return &domain.InvalidError{Code: domain.CodeInvalidDelegate, Detail: fmt.Sprintf(
				"Delegate '%s': auth_secret_name is only sent to an a2a_url.", t.Name)}
		default:
			id, err := s.delegateAgentID(ctx, ws, t.Name, st.AgentID)
			if err != nil {
				return err
			}
			st.AgentID = &id
		}
		tools[i].Settings = &st
	}
	for b := range credentialBindings(tools) {
		if !credentialBindings(previous)[b] {
			return &UnwiredError{Feature: "sending a workspace secret to a remote delegate"}
		}
	}
	return nil
}

func validHTTPURL(u string) bool {
	rest, ok := strings.CutPrefix(u, "https://")
	if !ok {
		rest, ok = strings.CutPrefix(u, "http://")
	}
	if !ok {
		return false
	}
	host, _, _ := strings.Cut(rest, "/")
	host = host[strings.LastIndex(host, "@")+1:]
	if strings.HasPrefix(host, "[") {
		return len(host) > 2
	}
	host, _, _ = strings.Cut(host, ":")
	return host != ""
}

func (s *Service) validateCodeNames(tools []domain.Tool) error {
	if s.d.CodeTools == nil {
		return nil
	}
	avail := s.d.CodeTools.Names()
	var bad []string
	for _, t := range tools {
		if t.Type == domain.ToolCode && !slices.Contains(avail, t.Name) {
			bad = append(bad, t.Name)
		}
	}
	if len(bad) == 0 {
		return nil
	}
	return &domain.InvalidError{Code: domain.CodeInvalidCodeTools, Detail: fmt.Sprintf(
		"Invalid code tools: %s. Available tools: %s", pyList(bad), pyList(avail))}
}

func pyList(v []string) string {
	q := make([]string, len(v))
	for i, s := range v {
		q[i] = "'" + s + "'"
	}
	return "[" + strings.Join(q, ", ") + "]"
}

func (s *Service) resolveSlug(ctx context.Context, sess db.Session, name string) (string, error) {
	base := domain.Slug(name)
	for i := 1; i <= domain.MaxSlugSuffix; i++ {
		cand := base
		if i > 1 {
			cand = fmt.Sprintf("%s-%d", base, i)
		}
		_, taken, err := s.store.BySlug(ctx, sess, cand)
		if err != nil {
			return "", err
		}
		if !taken {
			return cand, nil
		}
	}
	return "", fmt.Errorf("exhausted collision suffixes (-2..-999) for slug base '%s'", base)
}

func (s *Service) skillsExist(ctx context.Context, sess db.Session, ids []string) ([]uuid.UUID, error) {
	out := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		u := uuid.MustParse(id)
		ok, err := store.Lookup{}.SkillExists(ctx, sess, u)
		if err != nil {
			return nil, err
		}
		if !ok {
			return nil, &domain.NotFoundError{Message: fmt.Sprintf("Skill %s not found", u)}
		}
		out = append(out, u)
	}
	return out, nil
}

// untickedTargets is unticked_targets: the rule targets of the listed tools
// that the config leaves without approval.
func untickedTargets(tools []domain.Tool) []string {
	set := map[string]bool{}
	for _, t := range tools {
		if t.Type == domain.ToolMCP {
			if t.Settings == nil || t.Settings.MCPAllowed == nil {
				continue
			}
			for _, p := range *t.Settings.MCPAllowed {
				if (p.RequiresUserConfirmation != nil && *p.RequiresUserConfirmation) || p.ToolName == "" || t.Name == "" {
					continue
				}
				set["tool:mcp:"+t.Name+":"+p.ToolName], set["tool:"+p.ToolName] = true, true
			}
			continue
		}
		if t.Settings != nil && t.Settings.RequiresUserConfirmation != nil && *t.Settings.RequiresUserConfirmation || t.Name == "" {
			continue
		}
		set["tool:"+t.Name[strings.LastIndex(t.Name, "/")+1:]] = true
	}
	return sortedKeys(set)
}
