package service

import (
	"context"
	"errors"
	"fmt"
	"strings"

	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

func (t BundleTask) specKey() string         { return t.Key }
func (t BundleTask) renamedFrom() *string    { return t.RenamedFrom }
func (p BundleProject) specKey() string      { return p.Key }
func (p BundleProject) renamedFrom() *string { return p.RenamedFrom }

func taskDetail(t BundleTask) string { return fmt.Sprintf("runs agent '%s'", t.Agent) }

func projectDeps(p BundleProject) []entityRef {
	var out []entityRef
	for _, g := range []struct {
		kind EntityKind
		keys []string
	}{{KindAgent, p.Agents}, {KindMCP, p.MCPs}, {KindSkill, p.Skills}} {
		for _, k := range g.keys {
			out = append(out, entityRef{g.kind, k})
		}
	}
	return out
}

func projectDetail(p BundleProject) string {
	var parts []string
	for _, g := range []struct {
		n    int
		noun string
	}{{len(p.Agents), "agent"}, {len(p.MCPs), "MCP server"}, {len(p.Skills), "skill"}} {
		if g.n > 0 {
			parts = append(parts, counted(g.n, g.noun))
		}
	}
	if len(parts) == 0 {
		return "groups nothing yet"
	}
	return strings.Join(parts, ", ")
}

func (a *bundleAnalyzer) analyzeTasks(ctx context.Context, b *Bundle, agentKeys map[string]bool, entities *[]PreviewEntity, issues *[]PreviewIssue) error {
	for _, t := range b.Tasks {
		if !agentKeys[t.Agent] {
			*issues = append(*issues, blockIssue(t.Key, fmt.Sprintf("task '%s' references unknown agent '%s'", t.Key, t.Agent)))
		}
		status, err := a.plan(ctx, KindTask, t, []entityRef{{KindAgent, t.Agent}}, nil)
		if err != nil {
			return err
		}
		*entities = append(*entities, PreviewEntity{Kind: KindTask, Key: t.Key, Name: t.Name, Status: status, Detail: strp(taskDetail(t))})
	}
	return nil
}

func (a *bundleAnalyzer) analyzeProjects(ctx context.Context, b *Bundle, keys map[EntityKind]map[string]bool, entities *[]PreviewEntity,
	issues *[]PreviewIssue) error {
	for _, p := range b.Projects {
		for _, d := range projectDeps(p) {
			if !keys[d.kind][d.key] {
				*issues = append(*issues, blockIssue(p.Key, fmt.Sprintf("project '%s' references unknown %s '%s'", p.Key, d.kind, d.key)))
			}
		}
		status, err := a.plan(ctx, KindProject, p, projectDeps(p), nil)
		if err != nil {
			return err
		}
		*entities = append(*entities, PreviewEntity{Kind: KindProject, Key: p.Key, Name: p.Name, Status: status, Detail: strp(projectDetail(p))})
	}
	return nil
}

func (in *bundleInstaller) taskSpec(t BundleTask, agentID string) catalogapi.BundleTaskSpec {
	return catalogapi.BundleTaskSpec{Name: t.Name, Prompt: resolvePlaceholders(t.Prompt, in.values), AgentID: agentID,
		Parameters: plainObject(t.Parameters)}
}

func (in *bundleInstaller) installTasks(ctx context.Context) error {
	w := in.w
	tk := w.b.d.Tasks
	in.taskIDs = map[string]string{}
	for _, t := range in.pkg.Tasks {
		agentID, ok := in.agentIDs[t.Agent]
		if !ok {
			if err := in.addSkipped(KindTask, t.Key, t.Name, fmt.Sprintf("agent '%s' was not created", t.Agent)); err != nil {
				return err
			}
			continue
		}
		detail := taskDetail(t)
		fp, err := in.fingerprint(t)
		if err != nil {
			return err
		}
		id, _, err := in.owned(ctx, KindTask, t.Key)
		if err != nil {
			return err
		}
		if id != nil {
			update, err := in.needsUpdate(KindTask, t, []entityRef{{KindAgent, t.Agent}})
			if err != nil {
				return err
			}
			action := ActionUnchanged
			if update {
				if err := in.authorizeUpdate(ctx, KindTask, t.Key, *id); err != nil {
					return err
				}
				err := tk.UpdateTask(ctx, w.c, *id, in.taskSpec(t, agentID))
				if errors.Is(err, catalogapi.ErrBundleEntityGone) {
					return installError(fmt.Sprintf("task '%s' disappeared mid-update", t.Key))
				}
				if err := refusedInstall(err); err != nil {
					return err
				}
				in.updatedInPlace = true
				action = ActionUpdated
			}
			in.taskIDs[t.Key] = *id
			in.add(InstalledEntity{Kind: KindTask, Key: t.Key, Name: t.Name, Action: action, ID: id, Detail: &detail, Fingerprint: fp})
			continue
		}
		reused, err := in.reused(ctx, KindTask, t.Key)
		if err != nil {
			return err
		}
		if reused != nil {
			in.taskIDs[t.Key] = *reused
			in.add(reusedEntity(KindTask, t.Key, t.Name, *reused))
			continue
		}
		made, err := tk.CreateTask(ctx, w.c, in.taskSpec(t, agentID))
		if err != nil {
			return refusedInstall(err)
		}
		in.track(fmt.Sprintf("task '%s'", t.Name), func(ctx context.Context) error { return tk.DeleteTask(ctx, w.c, made) })
		in.taskIDs[t.Key] = made
		in.add(InstalledEntity{Kind: KindTask, Key: t.Key, Name: t.Name, Action: ActionCreated, ID: &made, Detail: &detail, Fingerprint: fp})
	}
	return nil
}

// projectSpec is p with the ids its keys resolve to; ids reads them from this
// deploy's writes, or from what the last install linked.
func projectSpec(p BundleProject, ids func(EntityKind, []string) []string) catalogapi.BundleProjectSpec {
	out := catalogapi.BundleProjectSpec{Name: p.Name, Instructions: p.Instructions, AgentIDs: ids(KindAgent, p.Agents),
		MCPInstanceIDs: ids(KindMCP, p.MCPs), SkillIDs: ids(KindSkill, p.Skills)}
	if p.Description != "" {
		out.Description = strp(p.Description)
	}
	return out
}

func (in *bundleInstaller) linkedNow(kind EntityKind, keys []string) []string {
	byKind := map[EntityKind]map[string]string{KindAgent: in.agentIDs, KindMCP: in.mcpIDs, KindSkill: in.skillIDs}[kind]
	out := []string{}
	for _, k := range keys {
		if id, ok := byKind[k]; ok {
			out = append(out, id)
		}
	}
	return out
}

func (in *bundleInstaller) installProjects(ctx context.Context) error {
	w := in.w
	pj := w.b.d.Projects
	for _, p := range in.pkg.Projects {
		detail := projectDetail(p)
		fp, err := in.fingerprint(p)
		if err != nil {
			return err
		}
		spec := projectSpec(p, in.linkedNow)
		id, _, err := in.owned(ctx, KindProject, p.Key)
		if err != nil {
			return err
		}
		if id != nil {
			update, err := in.needsUpdate(KindProject, p, projectDeps(p))
			if err != nil {
				return err
			}
			action := ActionUnchanged
			if update {
				if err := in.authorizeUpdate(ctx, KindProject, p.Key, *id); err != nil {
					return err
				}
				var managed catalogapi.BundleProjectSpec
				if before, ok := in.prior.spec(KindProject, p.Key).(BundleProject); ok {
					managed = projectSpec(before, in.linkedBefore)
				}
				err := pj.UpdateProject(ctx, w.c, *id, spec, managed)
				if errors.Is(err, catalogapi.ErrBundleEntityGone) {
					return installError(fmt.Sprintf("project '%s' disappeared mid-update", p.Key))
				}
				if err := refusedInstall(err); err != nil {
					return err
				}
				in.updatedInPlace = true
				action = ActionUpdated
			}
			in.add(InstalledEntity{Kind: KindProject, Key: p.Key, Name: p.Name, Action: action, ID: id, Detail: &detail, Fingerprint: fp})
			continue
		}
		reused, err := in.reused(ctx, KindProject, p.Key)
		if err != nil {
			return err
		}
		if reused != nil {
			in.add(reusedEntity(KindProject, p.Key, p.Name, *reused))
			continue
		}
		made, err := pj.CreateProject(ctx, w.c, spec)
		if err != nil {
			return refusedInstall(err)
		}
		in.track(fmt.Sprintf("project '%s'", p.Name), func(ctx context.Context) error { return pj.DeleteProject(ctx, w.c, made) })
		in.add(InstalledEntity{Kind: KindProject, Key: p.Key, Name: p.Name, Action: ActionCreated, ID: &made, Detail: &detail, Fingerprint: fp})
	}
	return nil
}

// bundleTask is the bundle's task auto runs, false when it runs none of them.
func bundleTask(b *Bundle, auto BundleAutomation) (BundleTask, bool) {
	if auto.Task == nil {
		return BundleTask{}, false
	}
	for _, t := range b.Tasks {
		if t.Key == *auto.Task {
			return t, true
		}
	}
	return BundleTask{}, false
}

// automationAgent is the agent key auto runs: its task's, else its own; "" for a workspace's saved task.
func automationAgent(b *Bundle, auto BundleAutomation) string {
	if t, ok := bundleTask(b, auto); ok {
		return t.Agent
	}
	if auto.Task != nil {
		return ""
	}
	return auto.Agent
}

func strangerTask(auto BundleAutomation) string {
	return fmt.Sprintf("automation '%s' runs task '%s', which is neither a task of this bundle nor a saved task of the workspace", auto.Key, *auto.Task)
}

// automationAgentID is the agent auto's trigger runs, nil when this deploy
// creates it; it blocks a task or agent the plan cannot bind.
func (a *bundleAnalyzer) automationAgentID(ctx context.Context, b *Bundle, auto BundleAutomation, agentKeys map[string]bool,
	issues *[]PreviewIssue) (*string, error) {
	block := func(format string, args ...any) {
		*issues = append(*issues, blockIssue(auto.Key, fmt.Sprintf(format, args...)))
	}
	if t, ok := bundleTask(b, auto); ok {
		if auto.Agent != "" && auto.Agent != t.Agent {
			block("automation '%s' runs task '%s', whose agent is '%s', not '%s'", auto.Key, t.Key, t.Agent, auto.Agent)
		}
		return a.plannedID(KindAgent, t.Agent), nil
	}
	if auto.Task == nil {
		if !agentKeys[auto.Agent] {
			block("automation '%s' references unknown agent '%s'", auto.Key, auto.Agent)
		}
		return a.plannedID(KindAgent, auto.Agent), nil
	}
	if a.checks == nil {
		return nil, nil
	}
	refs, err := a.existence.taskNamed(ctx, *auto.Task)
	if err != nil {
		return nil, err
	}
	switch len(refs) {
	case 0:
		block("%s", strangerTask(auto))
		return nil, nil
	case 1:
	default:
		block("automation '%s' runs task '%s', but %d saved tasks have that name; rename one", auto.Key, *auto.Task, len(refs))
		return nil, nil
	}
	if auto.Agent != "" {
		if id := a.plannedID(KindAgent, auto.Agent); id == nil || *id != refs[0].AgentID {
			block("automation '%s' runs saved task '%s', whose agent is %s, not '%s'", auto.Key, *auto.Task, refs[0].AgentID, auto.Agent)
		}
	}
	return &refs[0].AgentID, nil
}

// automationTarget is the agent and saved task auto's trigger runs; ok false when the agent was not created.
func (in *bundleInstaller) automationTarget(ctx context.Context, auto BundleAutomation) (agentID string, taskID *string, ok bool, err error) {
	if auto.Task == nil {
		agentID, ok = in.agentIDs[auto.Agent]
		return agentID, nil, ok, nil
	}
	if t, isBundle := bundleTask(in.pkg, auto); isBundle {
		id, created := in.taskIDs[t.Key]
		agentID, ok = in.agentIDs[t.Agent]
		return agentID, &id, ok && created, nil
	}
	refs, err := in.w.b.d.Tasks.TaskNamed(ctx, in.w.c, *auto.Task)
	if err != nil {
		return "", nil, false, err
	}
	if len(refs) != 1 {
		msg := strangerTask(auto)
		return "", nil, false, installError(msg, blockIssue(auto.Key, msg))
	}
	return refs[0].AgentID, &refs[0].ID, true, nil
}
