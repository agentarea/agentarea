package service

import (
	"context"
	"errors"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// BundleAgents is what a bundle deploy reads and writes of agents and skills.
type BundleAgents struct{ K *Skills }

var _ catalogapi.BundleAgents = BundleAgents{}

func (b BundleAgents) svc() *Service { return b.K.s }

// bundleRefusal turns the errors Python raises as ValueError into the deploy's refusal.
func bundleRefusal(err error) error {
	var value *domain.SkillValueError
	var front *SkillFrontmatterError
	var gh *domain.SkillGitHubError
	var invalid *domain.InvalidError
	switch {
	case errors.As(err, &value), errors.As(err, &front), errors.As(err, &gh), errors.As(err, &invalid):
		return &catalogapi.BundleRefusal{Msg: err.Error()}
	case errors.Is(err, domain.ErrReasoningConflict):
		return &catalogapi.BundleRefusal{Msg: err.Error()}
	}
	return err
}

func bundleTool(t catalogapi.BundleTool) domain.Tool {
	out := domain.Tool{Type: t.Type, Name: t.Name}
	switch {
	case t.AgentID != nil:
		out.Settings = &domain.Settings{AgentID: t.AgentID}
	case t.ConnectionID != nil:
		out.Settings = &domain.Settings{OpenAPIConnectionID: t.ConnectionID}
	}
	return out
}

func bundleTools(tools []catalogapi.BundleTool) []domain.Tool {
	out := make([]domain.Tool, len(tools))
	for i, t := range tools {
		out[i] = bundleTool(t)
	}
	return out
}

func (b BundleAgents) AgentLive(ctx context.Context, c authn.Caller, id string) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	a, ok, err := b.svc().load(ctx, c.Workspace, u, false)
	if err != nil || !ok {
		return false, err
	}
	return a.Status != domain.StatusArchived, nil
}

func (b BundleAgents) AgentProblem(ctx context.Context, c authn.Caller, cfg catalogapi.BundleAgentConfig) (string, error) {
	s := b.svc()
	if s.d.CodeTools == nil {
		return "", &UnwiredError{Feature: "the code toolset registry"}
	}
	known := s.d.CodeTools.Names()
	var unknown []string
	for _, n := range cfg.Toolsets {
		if !slices.Contains(known, n) {
			unknown = append(unknown, n)
		}
	}
	if len(unknown) > 0 {
		return "unknown toolset(s): " + strings.Join(unknown, ", "), nil
	}
	var client *string
	if cfg.ClientID != nil && *cfg.ClientID != "" {
		u, err := uuid.Parse(*cfg.ClientID)
		if err != nil {
			return "client must be the id of a Codex or Claude Code client", nil
		}
		client = new(string)
		*client = u.String()
	}
	tools := make([]domain.Tool, len(cfg.Toolsets))
	for i, n := range cfg.Toolsets {
		tools[i] = domain.Tool{Type: domain.ToolCode, Name: n}
	}
	problem := func(err error) (string, error) {
		var invalid *domain.InvalidError
		if errors.As(err, &invalid) {
			return invalid.Detail, nil
		}
		return "", err
	}
	if err := s.validateToolModels(ctx, c.Workspace, tools); err != nil {
		return problem(err)
	}
	modelID := cfg.ModelID
	if _, err := s.validateModelID(ctx, c.Workspace, &modelID); err != nil {
		return problem(err)
	}
	if _, err := s.validateClientID(ctx, c.Workspace, c, client); err != nil {
		return problem(err)
	}
	if truthy(cfg.ReasoningEffort) && cfg.ReasoningMaxTokens != nil && *cfg.ReasoningMaxTokens != 0 {
		return domain.ErrReasoningConflict.Error(), nil
	}
	return "", nil
}

func (b BundleAgents) CreateAgent(ctx context.Context, c authn.Caller, in catalogapi.BundleAgentNew) (string, error) {
	modelID := in.ModelID
	v, err := b.svc().Create(ctx, c, Create{Name: in.Name, Description: in.Description, Instruction: in.Instruction, ModelID: &modelID,
		ClientID: in.ClientID, Tools: bundleTools(in.Tools), SkillIDs: in.SkillIDs, ReasoningEffort: in.ReasoningEffort,
		ReasoningMaxTokens: in.ReasoningMaxTokens, AgentType: "stateless"})
	if err != nil {
		return "", bundleRefusal(err)
	}
	return v.Agent.ID, nil
}

// bundleToolsAfter are the agent's tools once a redeploy applies in: the
// managed ones replaced by what the folder declares, the ones added in the
// workspace kept. A delegate is matched by the agent it reaches, then by name,
// and keeps the settings set on it; only its name and agent id follow the folder.
func bundleToolsAfter(current []domain.Tool, in catalogapi.BundleAgentUpdate) []domain.Tool {
	type ref struct{ typ, name string }
	managed, wanted := map[ref]bool{}, map[ref]bool{}
	managedAgents := map[string]bool{}
	byAgent, byName := map[string]catalogapi.BundleTool{}, map[string]catalogapi.BundleTool{}
	for _, t := range append(append([]catalogapi.BundleTool{}, in.ManagedTools...), in.Tools...) {
		managed[ref{t.Type, t.Name}] = true
		if t.Type == domain.ToolAgent && t.AgentID != nil {
			managedAgents[*t.AgentID] = true
		}
	}
	for _, t := range in.Tools {
		wanted[ref{t.Type, t.Name}] = true
		if t.Type == domain.ToolAgent {
			byName[t.Name] = t
			if t.AgentID != nil {
				byAgent[*t.AgentID] = t
			}
		}
	}
	var tools []domain.Tool
	present := map[ref]bool{}
	for _, t := range current {
		r := ref{t.Type, t.Name}
		if t.Type != domain.ToolAgent {
			if wanted[r] || !managed[r] {
				tools = append(tools, t)
				present[r] = true
			}
			continue
		}
		agentID := ""
		if t.Settings != nil && t.Settings.AgentID != nil {
			agentID = *t.Settings.AgentID
		}
		isManaged := managed[r] || managedAgents[agentID]
		d, ok := byAgent[agentID]
		if !ok && isManaged {
			d, ok = byName[t.Name]
		}
		if ok && !present[ref{d.Type, d.Name}] {
			st := domain.Settings{}
			if t.Settings != nil {
				st = *t.Settings
			}
			st.AgentID = d.AgentID
			tools = append(tools, domain.Tool{Type: t.Type, Name: d.Name, Settings: &st})
			present[ref{d.Type, d.Name}] = true
			continue
		}
		if !isManaged {
			tools = append(tools, t)
			present[r] = true
		}
	}
	for _, t := range in.Tools {
		if r := (ref{t.Type, t.Name}); !present[r] {
			tools = append(tools, bundleTool(t))
			present[r] = true
		}
	}
	if tools == nil {
		tools = []domain.Tool{}
	}
	return tools
}

// UpdateAgent applies the folder to the agent: the tools and skills it
// manages replaced, the ones added in the workspace kept, approvals as they were.
func (b BundleAgents) UpdateAgent(ctx context.Context, c authn.Caller, id string, in catalogapi.BundleAgentUpdate) error {
	s := b.svc()
	u, err := uuid.Parse(id)
	if err != nil {
		return domain.ErrAgentNotFound
	}
	a, ok, err := s.load(ctx, c.Workspace, u, true)
	if err != nil {
		return err
	}
	if !ok {
		return catalogapi.ErrBundleEntityGone
	}
	views, err := s.views(ctx, c.Workspace, []domain.Agent{a})
	if err != nil {
		return err
	}
	tools := bundleToolsAfter(views[0].Tools, in)
	managedSkills := map[string]bool{}
	for _, id := range append(append([]string{}, in.ManagedSkillIDs...), in.SkillIDs...) {
		managedSkills[id] = true
	}
	skillIDs := []string{}
	for _, sk := range a.Skills {
		if !managedSkills[sk.ID] || slices.Contains(in.SkillIDs, sk.ID) {
			skillIDs = append(skillIDs, sk.ID)
		}
	}
	for _, sid := range in.SkillIDs {
		if !slices.Contains(skillIDs, sid) {
			skillIDs = append(skillIDs, sid)
		}
	}
	name, modelID := in.Name, in.ModelID
	p := Patch{Name: &name, Description: Set[string]{Set: true, Value: &in.Description},
		Instruction: Set[string]{Set: true, Value: &in.Instruction}, ModelID: Set[string]{Set: true, Value: &modelID},
		Tools: &tools, SkillIDs: &skillIDs}
	if in.SetReasoning {
		p.ReasoningEffort = Set[string]{Set: true, Value: in.ReasoningEffort}
		p.ReasoningMaxTokens = Set[int32]{Set: true, Value: in.ReasoningMaxTokens}
	}
	if in.SetClient {
		p.ClientID = Set[string]{Set: true, Value: in.ClientID}
	}
	_, err = s.Update(ctx, c, id, p)
	return bundleRefusal(err)
}

func (b BundleAgents) DeleteAgent(ctx context.Context, c authn.Caller, id string) error {
	s := b.svc()
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	a, ok, err := s.load(ctx, c.Workspace, u, false)
	if err != nil || !ok {
		return err
	}
	return s.unmake(ctx, c, id, toolsFromColumn(a.Tools))
}

func (b BundleAgents) SkillLive(ctx context.Context, c authn.Caller, id string) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	_, err = b.K.Get(ctx, c, u)
	switch {
	case err == nil:
		return true, nil
	case errors.Is(err, ErrSkillNotFound), errors.As(err, new(*SkillNotFoundError)):
		return false, nil
	}
	return false, err
}

func (BundleAgents) SkillProblem(content string) string {
	if _, err := SkillParse(content); err != nil {
		return err.Error()
	}
	return ""
}

func (BundleAgents) SkillMainFile(paths []string) (string, bool) { return domain.SkillMainFile(paths) }

func (b BundleAgents) CreateSkill(ctx context.Context, c authn.Caller, in catalogapi.BundleSkillNew) (string, error) {
	name := in.Name
	var v SkillView
	var err error
	switch {
	case in.GitHubURL != "":
		v, err = b.K.CreateFromGitHub(ctx, c, in.GitHubURL, &name, nil)
	case len(in.Files) > 0:
		var fs domain.SkillFiles
		for _, f := range in.Files {
			fs.Set(f.Path, []byte(f.Text))
		}
		data, zerr := domain.SkillZip(fs)
		if zerr != nil {
			return "", zerr
		}
		v, err = b.K.CreateFromZip(ctx, c, data, &name, nil)
	default:
		v, err = b.K.CreateFromContent(ctx, c, in.Content, &name, nil)
	}
	if err != nil {
		return "", bundleRefusal(err)
	}
	return v.ID, nil
}

func (b BundleAgents) ReplaceSkillFiles(ctx context.Context, c authn.Caller, id string, files []catalogapi.BundleFile) error {
	texts := make([]api.SkillFileText, len(files))
	for i, f := range files {
		texts[i] = api.SkillFileText{Path: f.Path, Text: f.Text}
	}
	_, err := SkillToolset(b).ReplaceFiles(ctx, c, id, texts)
	return bundleRefusal(err)
}

func (b BundleAgents) RenameSkill(ctx context.Context, c authn.Caller, id, name string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	_, err = b.K.Update(ctx, c, u, &name, nil, nil)
	return bundleRefusal(err)
}

func (b BundleAgents) DeleteSkill(ctx context.Context, c authn.Caller, id string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	return b.K.Delete(ctx, c, u)
}
