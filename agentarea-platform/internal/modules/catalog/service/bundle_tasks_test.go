package service

import (
	"context"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

type fakeBundleTasks struct {
	log   *deployLog
	names map[string]string
	// agents are the agent of each saved task the workspace had before the deploy.
	agents map[string]string
	n      int
}

func (f *fakeBundleTasks) TaskNamed(_ context.Context, _ authn.Caller, name string) ([]catalogapi.BundleTaskRef, error) {
	var out []catalogapi.BundleTaskRef
	for id, n := range f.names {
		if n == name {
			out = append(out, catalogapi.BundleTaskRef{ID: id, AgentID: f.agents[id]})
		}
	}
	return out, nil
}

func (f *fakeBundleTasks) TaskName(_ context.Context, _ authn.Caller, id string) (string, bool, error) {
	n, ok := f.names[id]
	return n, ok, nil
}
func (f *fakeBundleTasks) CreateTask(_ context.Context, _ authn.Caller, s catalogapi.BundleTaskSpec) (string, error) {
	f.n++
	id := fmt.Sprintf("task-%d", f.n)
	f.names[id] = s.Name
	f.log.add("create task %s %s for %s prompt=%q params=%v", id, s.Name, s.AgentID, s.Prompt, s.Parameters)
	return id, nil
}
func (f *fakeBundleTasks) UpdateTask(_ context.Context, _ authn.Caller, id string, s catalogapi.BundleTaskSpec) error {
	f.log.add("update task %s %s for %s prompt=%q", id, s.Name, s.AgentID, s.Prompt)
	return nil
}
func (f *fakeBundleTasks) DeleteTask(_ context.Context, _ authn.Caller, id string) error {
	delete(f.names, id)
	f.log.add("delete task %s", id)
	return nil
}

type fakeBundleProjects struct {
	log   *deployLog
	names map[string]string
	n     int
}

func (f *fakeBundleProjects) ProjectName(_ context.Context, _ authn.Caller, id string) (string, bool, error) {
	n, ok := f.names[id]
	return n, ok, nil
}

func projectText(s catalogapi.BundleProjectSpec) string {
	sorted := func(l []string) string {
		out := append([]string{}, l...)
		sort.Strings(out)
		return strings.Join(out, ",")
	}
	return fmt.Sprintf("%s agents[%s] mcp[%s] skills[%s]", s.Name, sorted(s.AgentIDs), sorted(s.MCPInstanceIDs), sorted(s.SkillIDs))
}

func (f *fakeBundleProjects) CreateProject(_ context.Context, _ authn.Caller, s catalogapi.BundleProjectSpec) (string, error) {
	f.n++
	id := fmt.Sprintf("project-%d", f.n)
	f.names[id] = s.Name
	f.log.add("create project %s %s", id, projectText(s))
	return id, nil
}
func (f *fakeBundleProjects) UpdateProject(_ context.Context, _ authn.Caller, id string, s, managed catalogapi.BundleProjectSpec) error {
	f.log.add("update project %s %s managed %s", id, projectText(s), projectText(managed))
	return nil
}
func (f *fakeBundleProjects) DeleteProject(_ context.Context, _ authn.Caller, id string) error {
	delete(f.names, id)
	f.log.add("delete project %s", id)
	return nil
}

const tasksBundle = `
name: ops
skills:
  - {key: notes, name: Notes, content: "---\nname: notes\ndescription: n\n---\nBody"}
agents:
  - {key: triage, name: Triage, model: us-model, skills: [notes]}
  - {key: writer, name: Writer, model: us-model}
tasks:
  - {key: weekly-report, name: Weekly report, agent: writer, prompt: "Write the weekly report", parameters: {week: current}}
projects:
  - {key: support, name: Support, description: Inbound work, agents: [triage, writer], skills: [notes]}
`

func TestLoadTasksAndProjectsFromAFolder(t *testing.T) {
	b, issues, err := LoadBundleFolder(StrPairs{
		{EntryFile, "schema_version: 1\nname: ops\nagents:\n  include: agents/*.md\ntasks:\n  include: tasks/*.md\n" +
			"projects:\n  include: projects/*.yaml\n  sales:\n    agents: [triage]\n"},
		{"agents/triage.md", "---\nname: triage\nmodel: us-model\n---\nTriage."},
		{"tasks/weekly-report.md", "---\nname: weekly-report\ndisplay_name: Weekly report\nagent: triage\nparameters: {week: current}\n---\nWrite the weekly report.\n"},
		{"projects/support.yaml", "name: support\ndisplay_name: Support\ndescription: Inbound work\ninstructions: Be kind\nagents: [triage]\n"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 {
		t.Fatalf("issues = %+v", issues)
	}
	task := b.Tasks[0]
	if len(b.Tasks) != 1 || task.Key != "weekly-report" || task.Name != "Weekly report" || task.Agent != "triage" || task.Prompt != "Write the weekly report." {
		t.Fatalf("tasks = %+v", b.Tasks)
	}
	if len(b.Projects) != 2 || b.Projects[0].Key != "sales" || b.Projects[1].Name != "Support" || *b.Projects[1].Instructions != "Be kind" ||
		!reflect.DeepEqual(b.Projects[1].Agents, []string{"triage"}) {
		t.Fatalf("projects = %+v", b.Projects)
	}
	for _, c := range []struct{ name, file, want string }{
		{"no agent", "---\nname: t\n---\nGo", "task 't' needs agent, the key of the agent it runs"},
		{"no prompt", "---\nname: t\nagent: triage\n---\n", "task 't' needs a prompt: the body of the file"},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, _, err := LoadBundleFolder(StrPairs{{EntryFile, "schema_version: 1\nname: ops\nagents:\n  include: agents/*.md\ntasks:\n  include: tasks/*.md\n"},
				{"agents/triage.md", "---\nname: triage\nmodel: m\n---\n"}, {"tasks/t.md", c.file}})
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("err = %v", err)
			}
		})
	}
}

func TestTaskAndProjectPlanChecksReferences(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, tasksBundle, nil)
	if len(p.Issues) != 0 {
		t.Fatalf("issues = %+v", p.Issues)
	}
	var got []string
	for _, e := range p.Entities {
		if e.Kind == KindTask || e.Kind == KindProject {
			got = append(got, fmt.Sprintf("%s:%s:%s:%s", e.Kind, e.Key, e.Status, *e.Detail))
		}
	}
	want := []string{"task:weekly-report:will_create:runs agent 'writer'", "project:support:will_create:2 agents, 1 skill"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("entities = %q", got)
	}
	p = analyzeWith(t, f, `
name: ops
agents: [{key: a, name: A, model: us-model}]
tasks: [{key: t, name: T, agent: ghost, prompt: go}]
projects: [{key: p, name: P, agents: [a, ghost], mcp: [none], skills: [nope]}]
`, nil)
	wantBlocks := []string{
		"task 't' references unknown agent 'ghost'",
		"project 'p' references unknown agent 'ghost'",
		"project 'p' references unknown mcp 'none'",
		"project 'p' references unknown skill 'nope'",
	}
	if got := blockMessages(p); !reflect.DeepEqual(got, wantBlocks) {
		t.Fatalf("blocks = %q", got)
	}
}

func TestTaskAndProjectInstallAndRedeploy(t *testing.T) {
	f := newDeployFixture(t)
	b := mustParse(t, tasksBundle)
	_, res, err := f.install(t, &b, nil)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, c := range f.log.calls {
		if strings.Contains(c, "task") || strings.Contains(c, "project") {
			got = append(got, c)
		}
	}
	want := []string{
		`create task task-1 Weekly report for agent-3 prompt="Write the weekly report" params=map[week:current]`,
		"create project project-1 Support agents[agent-2,agent-3] mcp[] skills[skill-1]",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("calls = %q", got)
	}
	prior := &priorInstall{bundle: b, result: res}
	changed := mustParse(t, strings.NewReplacer("agents: [triage, writer]", "agents: [triage]", `prompt: "Write the weekly report"`,
		`prompt: "Write the monthly report"`).Replace(tasksBundle))
	f.log.calls = nil
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{{KindTask, "weekly-report"}: true, {KindProject, "support"}: true}}
	if _, err := in.install(context.Background(), &changed, wirejson.Object{}, prior, nil); err != nil {
		t.Fatal(err)
	}
	want = []string{
		`update task task-1 Weekly report for agent-3 prompt="Write the monthly report"`,
		"update project project-1 Support agents[agent-2] mcp[] skills[skill-1] managed Support agents[agent-2,agent-3] mcp[] skills[skill-1]",
	}
	if !reflect.DeepEqual(f.log.calls, want) {
		t.Fatalf("calls = %q", f.log.calls)
	}
	if !reflect.DeepEqual(f.edits[len(f.edits)-1:], []string{"task_definition:task-1"}) {
		t.Errorf("edit checks = %v (a project's routes check no edit)", f.edits)
	}
}

const taskScheduleBundle = `
name: ops
agents:
  - {key: writer, name: Writer, model: us-model}
tasks:
  - {key: weekly-report, name: Weekly report, agent: writer, prompt: "Write the weekly report"}
automations:
  - {key: monday, task: weekly-report, cron: "0 9 * * 1", parameters: {week: last}}
  - {key: nightly, agent: writer, cron: "0 2 * * *", prompt: Sweep}
`

func TestScheduleRunsASavedTask(t *testing.T) {
	b, issues, err := LoadBundleFolder(StrPairs{
		{EntryFile, "schema_version: 1\nname: ops\nagents:\n  include: agents/*.md\ntasks:\n  include: tasks/*.md\nschedules:\n  include: schedules/*.md\n"},
		{"agents/writer.md", "---\nname: writer\nmodel: us-model\n---\n"},
		{"tasks/weekly-report.md", "---\nname: weekly-report\nagent: writer\n---\nWrite the weekly report"},
		{"schedules/monday.md", "---\nname: monday\ntask: weekly-report\ncron: '0 9 * * 1'\nparameters: {week: last}\n---\n"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if a := b.Automations[0]; len(issues) != 0 || a.Task == nil || *a.Task != "weekly-report" || a.Agent != "" || a.Prompt != "" {
		t.Fatalf("automation = %+v, issues %+v", a, issues)
	}
	for _, c := range []struct{ name, file, want string }{
		{"body", "---\nname: s\ntask: weekly-report\ncron: '0 9 * * 1'\n---\nGo", "schedule 's' runs task 'weekly-report', whose prompt it is; leave the body empty"},
		{"neither", "---\nname: s\ncron: '0 9 * * 1'\n---\nGo", "schedule 's' needs agent, the key of the agent it runs, or task, the saved task it runs"},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, _, err := LoadBundleFolder(StrPairs{{EntryFile, "schema_version: 1\nname: ops\nagents:\n  include: agents/*.md\nschedules:\n  include: schedules/*.md\n"},
				{"agents/writer.md", "---\nname: writer\nmodel: m\n---\n"}, {"schedules/s.md", c.file}})
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("err = %v", err)
			}
		})
	}
	if _, err := ParseBundle("name: x\nautomations: [{key: s, task: t, agent: a, prompt: go, cron: '* * * * *'}]\n"); err == nil ||
		!strings.Contains(err.Error(), "automation 's' runs task 't' or is asked prompt, not both") {
		t.Fatalf("task and prompt: %v", err)
	}
}

func TestTaskSchedulePlanChecksTheTaskAndItsAgent(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, taskScheduleBundle, nil)
	if len(p.Issues) != 0 {
		t.Fatalf("issues = %+v", p.Issues)
	}
	for _, e := range p.Entities {
		if e.Key == "monday" && *e.Detail != "cron '0 9 * * 1' (UTC), enabled=False; runs task weekly-report" {
			t.Fatalf("detail = %q", *e.Detail)
		}
	}
	f.agents.live["agent-legacy"] = true
	f.tasks.names["task-old"], f.tasks.agents = "Old report", map[string]string{"task-old": "agent-legacy"}
	p = analyzeWith(t, f, `
name: ops
agents:
  - {key: writer, name: Writer, model: us-model}
  - {key: editor, name: Editor, model: us-model}
tasks:
  - {key: weekly-report, name: Weekly report, agent: writer, prompt: go}
automations:
  - {key: a, task: weekly-report, agent: editor, cron: "0 9 * * 1"}
  - {key: b, task: ghost, cron: "0 9 * * 1"}
  - {key: c, task: Old report, cron: "0 9 * * 1"}
`, nil)
	want := []string{
		"automation 'a' runs task 'weekly-report', whose agent is 'writer', not 'editor'",
		"automation 'b' runs task 'ghost', which is neither a task of this bundle nor a saved task of the workspace",
	}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks = %q", got)
	}
}

func TestTaskScheduleInstallsAndSwitchesModeInPlace(t *testing.T) {
	f := newDeployFixture(t)
	b := mustParse(t, taskScheduleBundle)
	_, res, err := f.install(t, &b, nil)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, c := range f.log.calls {
		if strings.HasPrefix(c, "create schedule") || strings.HasPrefix(c, "create task") {
			got = append(got, c)
		}
	}
	want := []string{
		`create task task-1 Weekly report for agent-1 prompt="Write the weekly report" params=map[]`,
		`create schedule ops:monday runs task task-1 for agent-1 params=map[week:last] text=""`,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("calls = %q", got)
	}
	changed := mustParse(t, strings.Replace(taskScheduleBundle, `{key: monday, task: weekly-report, cron: "0 9 * * 1", parameters: {week: last}}`,
		`{key: monday, agent: writer, cron: "0 9 * * 1", prompt: "Write it yourself"}`, 1))
	prior := &priorInstall{bundle: b, result: res}
	p, err := (&bundleAnalyzer{existence: f.w, checks: f.w, prior: prior, shapes: fakeShapes{}, supplied: wirejson.Object{}}).analyze(context.Background(), &changed)
	if err != nil || len(p.Blocks()) != 0 {
		t.Fatalf("plan = %+v, %v (the runtime switches a trigger between task and prompt)", p.Issues, err)
	}
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{{KindAutomation, "monday"}: true}}
	if _, err := in.install(context.Background(), &changed, wirejson.Object{}, prior, nil); err != nil {
		t.Fatal(err)
	}
	u := f.triggers.updates[len(f.triggers.updates)-1]
	if !u.TaskDefinitionSet || u.TaskDefinitionID != nil || u.Text != "Write it yourself" || u.AgentID != "agent-1" {
		t.Fatalf("update = %+v", u)
	}
}
