package domain

import (
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
)

// ExportSkill is a skill of SkillService.list() with its SKILL.md text when
// the export inlines it.
type ExportSkill struct {
	ID, Name, Slug, SourceType, SourceURL string
	Content                               string
	IsCatalog                             bool
}

// ExportAgentSkill is a skill attached to an agent.
type ExportAgentSkill struct{ ID, Name string }

// ExportTool is one stored tool entry: Name is str(name), HasName false for a missing or null name.
type ExportTool struct {
	Type    any
	Name    string
	HasName bool
}

// ExportAgent is an agent of AgentService.list() with its skills loaded.
type ExportAgent struct {
	ID, Name, Instruction string
	Tools                 []ExportTool
	Skills                []ExportAgentSkill
}

// ExportMCP is an MCP server instance with its transport spec.
type ExportMCP struct {
	ID, Name string
	// Builtin is a catalog or platform-managed connection: never exported.
	Builtin bool
	// Spec is get_transport_spec_for_instance's result.
	Spec           YAMLMap
	EnvVars        []string
	ContextSigning bool
}

// ExportTrigger is a trigger of TriggerRepository.list_all().
type ExportTrigger struct {
	ID, Name, Kind, AgentID string
	HasConditions           bool
	// Text is task_parameters["text"], nil when absent.
	Text           any
	Cron, Timezone string
	Enabled        bool
}

// ExportInput is what the export reads.
type ExportInput struct {
	WorkspaceID, WorkspaceSlug, WorkspaceName string
	Skills                                    []ExportSkill
	Agents                                    []ExportAgent
	MCPs                                      []ExportMCP
	Triggers                                  []ExportTrigger
}

// ExportWarn receives the warnings the export logs for skipped triggers.
type ExportWarn func(msg string, args ...any)

func exportInvalid(format string, args ...any) error {
	return &api.ExportInvalidError{Msg: fmt.Sprintf(format, args...)}
}

type exportSetup struct{ fields []any }

func (s *exportSetup) add(key, label, typ, help string) {
	s.fields = append(s.fields, YAMLMap{{"key", key}, {"label", label}, {"type", typ}, {"required", true}, {"help", help}})
}

// ExportBundle is export_workspace's Bundle(...).model_dump(mode="json", exclude_none=True).
func ExportBundle(in ExportInput, warn ExportWarn) (YAMLMap, error) {
	skills, skillKeys, err := exportSkills(in.Skills)
	if err != nil {
		return nil, err
	}
	setup := &exportSetup{}
	mcps, mcpKeys, builtin, err := exportMCPs(in.MCPs, setup)
	if err != nil {
		return nil, err
	}
	agents, agentKeys, err := exportAgents(in.Agents, skillKeys, mcpKeys, builtin, setup)
	if err != nil {
		return nil, err
	}
	automations := exportAutomations(in.Triggers, agentKeys, warn)
	name := in.WorkspaceSlug
	if name == "" {
		name = ExportBundleKey("workspace", in.WorkspaceName, in.WorkspaceID)
	}
	orEmpty := func(v []any) []any {
		if v == nil {
			return []any{}
		}
		return v
	}
	return YAMLMap{
		{"schema_version", "0.1.0"},
		{"name", name},
		{"display_name", in.WorkspaceName},
		{"description", ""},
		{"metadata", YAMLMap{{"capabilities", []any{}}}},
		{"setup", orEmpty(setup.fields)},
		{"mcps", orEmpty(mcps)},
		{"skills", orEmpty(skills)},
		{"agents", orEmpty(agents)},
		{"channels", []any{}},
		{"automations", orEmpty(automations)},
		{"policies", []any{}},
	}, nil
}

func exportSkills(skills []ExportSkill) ([]any, map[string]string, error) {
	var out []any
	keys := map[string]string{}
	for _, s := range skills {
		if s.IsCatalog {
			continue
		}
		ref := s.Slug
		if ref == "" {
			ref = s.Name
		}
		key := ExportBundleKey("skill", ref, s.ID)
		if s.SourceType == "github" && s.SourceURL != "" {
			out = append(out, YAMLMap{{"key", key}, {"name", s.Name}, {"source_type", "github"}, {"source_url", s.SourceURL}})
		} else {
			if s.Content == "" {
				return nil, nil, exportInvalid("skill '%s' is source_type=content but has no content", key)
			}
			out = append(out, YAMLMap{{"key", key}, {"name", s.Name}, {"source_type", "content"}, {"content", s.Content}})
		}
		keys[s.ID] = key
	}
	return out, keys, nil
}

func exportPyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	case YAMLInt:
		return string(x)
	case YAMLFloat:
		return string(x)
	}
	return fmt.Sprint(v)
}

func exportMCPs(instances []ExportMCP, setup *exportSetup) ([]any, map[string]string, map[string]bool, error) {
	var out []any
	keys := map[string]string{}
	builtin := map[string]bool{}
	for _, inst := range instances {
		if inst.Builtin {
			builtin[inst.ID], builtin[inst.Name] = true, true
			continue
		}
		key := ExportBundleKey("mcp", inst.Name, inst.ID)
		specType, _ := yamlGet(inst.Spec, "type")
		if t, ok := specType.(string); !ok || (t != "command" && t != "docker" && t != "url") {
			return nil, nil, nil, exportInvalid("MCP instance '%s' uses unsupported transport '%s'", inst.Name, exportPyStr(specType))
		}
		name := inst.Name
		ref := func(field, what string) string {
			k := ExportSetupKey(field)
			setup.add(k, name+": "+what, "secret", "Provide "+what+" for "+name+".")
			return "${setup." + k + "}"
		}
		spec := YAMLMap{{"type", specType}}
		for _, f := range []string{"command", "image"} {
			if v, ok := yamlGet(inst.Spec, f); ok {
				spec = append(spec, YAMLItem{f, v})
			}
		}
		if v, ok := yamlGet(inst.Spec, "args"); ok {
			if args, isList := v.([]any); isList {
				spec = append(spec, YAMLItem{"args", ExportTemplateArgs(args, key, ref)})
			}
		}
		if v, ok := yamlGet(inst.Spec, "endpoint_url"); ok {
			if u, isStr := v.(string); isStr {
				if ExportURLCarriesCredentials(u) {
					u = ref(key+"_endpoint_url", "endpoint URL")
				}
				spec = append(spec, YAMLItem{"endpoint_url", u})
			}
		}
		bindings := YAMLMap{}
		bound := map[string]bool{}
		bind := func(name, value string) {
			bindings = append(bindings, YAMLItem{name, value})
			bound[name] = true
		}
		for _, env := range inst.EnvVars {
			if bound[env] {
				bindings.set(env, ref(key+"_"+env, env))
				continue
			}
			bind(env, ref(key+"_"+env, env))
		}
		for _, f := range []string{"environment", "headers"} {
			v, _ := yamlGet(inst.Spec, f)
			values, isMap := v.(YAMLMap)
			if !isMap {
				continue
			}
			plain := YAMLMap{}
			for _, it := range values {
				if bound[it.Key] {
					continue
				}
				var referenced any
				if m, isMap := it.Value.(YAMLMap); isMap {
					referenced, _ = yamlGet(m, "secret_name")
				}
				str, isStr := it.Value.(string)
				switch r, isRef := referenced.(string); {
				case isRef:
					bind(it.Key, "${secret."+r+"}")
				case ExportIsCredentialName(it.Key) || (isStr && ExportValueCarriesCredentials(str)):
					bind(it.Key, ref(key+"_"+it.Key, it.Key))
				default:
					plain.set(it.Key, it.Value)
				}
			}
			if len(plain) > 0 {
				spec = append(spec, YAMLItem{f, plain})
			}
		}
		item := YAMLMap{{"key", key}, {"name", inst.Name}, {"json_spec", spec}, {"bindings", bindings}}
		if specType == "url" && inst.ContextSigning {
			item = append(item, YAMLItem{"context_secret", ref(key+"_context_secret", "context signing secret")})
		}
		out = append(out, item)
		keys[inst.ID] = key
		keys[inst.Name] = key
	}
	return out, keys, builtin, nil
}

func yamlGet(m YAMLMap, key string) (any, bool) {
	for _, it := range m {
		if it.Key == key {
			return it.Value, true
		}
	}
	return nil, false
}

// set is dict assignment: a present key keeps its position.
func (m *YAMLMap) set(key string, v any) {
	for i := range *m {
		if (*m)[i].Key == key {
			(*m)[i].Value = v
			return
		}
	}
	*m = append(*m, YAMLItem{key, v})
}

func exportAgents(agents []ExportAgent, skillKeys, mcpKeys map[string]string, builtinMCP map[string]bool,
	setup *exportSetup) ([]any, map[string]string, error) {
	keys := map[string]string{}
	for _, a := range agents {
		keys[a.ID] = ExportBundleKey("agent", a.Name, a.ID)
	}
	var out []any
	for _, a := range agents {
		key := keys[a.ID]
		setupKey := ExportSetupKey("model_" + key)
		setup.fields = append(setup.fields, YAMLMap{{"key", setupKey}, {"label", "Model for " + a.Name}, {"type", "string"},
			{"required", true}, {"help", "Choose a model available in the destination workspace."}})
		skills := []any{}
		for _, s := range a.Skills {
			k, ok := skillKeys[s.ID]
			if !ok {
				return nil, nil, exportInvalid("Skill '%s' attached to agent '%s' could not be exported", s.Name, a.Name)
			}
			skills = append(skills, k)
		}
		toolsets, mcps := []any{}, []any{}
		has := func(list []any, v string) bool {
			for _, x := range list {
				if x == v {
					return true
				}
			}
			return false
		}
		for _, t := range a.Tools {
			if !t.HasName {
				continue
			}
			switch t.Type {
			case "code":
				if !has(toolsets, t.Name) {
					toolsets = append(toolsets, t.Name)
				}
			case "mcp":
				k, ok := mcpKeys[t.Name]
				if !ok {
					if builtinMCP[t.Name] {
						continue
					}
					return nil, nil, exportInvalid("MCP '%s' attached to agent '%s' could not be exported: it is not an MCP connection of this workspace", t.Name, a.Name)
				}
				if !has(mcps, k) {
					mcps = append(mcps, k)
				}
			}
		}
		out = append(out, YAMLMap{{"key", key}, {"name", a.Name}, {"description", ""}, {"instruction", a.Instruction},
			{"model", "${setup." + setupKey + "}"}, {"mcps", mcps}, {"skills", skills}, {"toolsets", toolsets}})
	}
	return out, keys, nil
}

func exportAutomations(triggers []ExportTrigger, agentKeys map[string]string, warn ExportWarn) []any {
	var out []any
	for _, t := range triggers {
		agentKey, ok := agentKeys[t.AgentID]
		if !ok {
			warn("Skipping trigger '%s' targeting an agent outside the bundle", t.Name)
			continue
		}
		if t.HasConditions {
			warn("Skipping trigger '%s' with conditions not represented in bundles", t.Name)
			continue
		}
		if t.Kind != "cron" {
			warn("Skipping unsupported trigger '%s' of type '%s'", t.Name, t.Kind)
			continue
		}
		prompt, isStr := t.Text.(string)
		if !isStr || strings.TrimFunc(prompt, exportPySpace) == "" {
			warn("Skipping cron trigger '%s' without task text", t.Name)
			continue
		}
		out = append(out, YAMLMap{{"key", ExportBundleKey("automation", t.Name, t.ID)}, {"type", "cron"}, {"cron", t.Cron},
			{"timezone", t.Timezone}, {"agent", agentKey}, {"prompt", prompt}, {"enabled", t.Enabled}})
	}
	return out
}
