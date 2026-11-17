package domain

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// FirstMessageIsTheTask replaces the goal in the system prompt when the run's
// input is the pinned first user message.
const FirstMessageIsTheTask = "The user's messages in this conversation are the task. The first one stays in view for " +
	"the whole run; act on the latest one, with the earlier ones as its context."

// SystemPrompt is PromptBuilder.build_system_prompt.
func SystemPrompt(agentName, instruction, goal string, criteria []string, a2ui bool, now time.Time) string {
	var kept []string
	for _, c := range criteria {
		if strings.TrimSpace(c) != "" {
			kept = append(kept, "- "+c)
		}
	}
	criteriaText := ""
	if len(kept) > 0 {
		criteriaText = "\n\n## Success Criteria\n\n" + strings.Join(kept, "\n")
	}
	prompt := strings.NewReplacer(
		"{agent_name}", agentName,
		"{agent_instruction}", instruction,
		"{goal_description}", goal,
		"{success_criteria}", criteriaText,
		"{started_at}", now.UTC().Format("2006-01-02 15:04"),
	).Replace(SystemPromptTemplate)
	if a2ui {
		prompt += A2UIPromptSection
	}
	return prompt
}

// SkillCatalog is SkillCatalogBuilder.build_catalog.
func SkillCatalog(skills []api.Skill) string {
	if len(skills) == 0 {
		return ""
	}
	lines := []string{
		"\n\n## Available Skills",
		"Skills provide specialized instructions for specific tasks.",
		"When a task matches a skill's description, use the `activate_skill` tool to load its full instructions.\n",
	}
	for _, s := range skills {
		desc := s.Description
		if desc == "" {
			desc = "No description"
		}
		lines = append(lines, fmt.Sprintf("- **%s**: %s", s.Name, desc))
	}
	return strings.Join(lines, "\n")
}

// WrapSkillContent is an activated skill's instructions as the model reads them.
func WrapSkillContent(name, body string, files []string) string {
	out := `<skill_content name="` + name + "\">\n" + body
	if len(files) > 0 {
		out += "\n\nSkill files:\n"
		for _, f := range files {
			out += "- " + f + "\n"
		}
	}
	return out + "</skill_content>"
}

// ToolSourceCatalog is ToolCatalog.build_prompt_text.
func ToolSourceCatalog(providers []api.ToolProvider, activated []string) string {
	if len(providers) == 0 {
		return ""
	}
	byName := map[string]api.ToolProvider{}
	var inactive []string
	for _, p := range providers {
		byName[p.Name] = p
	}
	for name := range byName {
		if !contains(activated, name) {
			inactive = append(inactive, name)
		}
	}
	if len(inactive) == 0 {
		return ""
	}
	sort.Strings(inactive)
	lines := []string{"\n\n## Available Tool Sources", "Use activate_tool_source(\"name\") to enable tools before using them.\n"}
	for _, name := range inactive {
		p := byName[name]
		names := make([]string, 0, len(p.Tools))
		for _, t := range p.Tools {
			names = append(names, t.Name)
		}
		preview := strings.Join(names[:min(5, len(names))], ", ")
		if len(names) > 5 {
			preview += ", ..."
		}
		lines = append(lines, fmt.Sprintf("- **%s** [%s] (%d tools): %s", p.Name, p.ProviderType, len(names), preview))
	}
	return strings.Join(lines, "\n")
}

// OpenAPICatalog is NamedLookupPolicy.render_catalog.
func OpenAPICatalog(pool []api.SearchableTool) string {
	if len(pool) == 0 {
		return ""
	}
	groups := map[string][]api.SearchableTool{}
	for _, c := range pool {
		key := c.ConnectionID
		if key == "" {
			key = "default"
		}
		groups[key] = append(groups[key], c)
	}
	keys := make([]string, 0, len(groups))
	for k := range groups {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	lines := []string{"", "## Available OpenAPI Operations", "Call " + ToolLoadTools + `(["name1","name2"]) with the exact operation names you need before invoking them.`}
	for _, k := range keys {
		lines = append(lines, "", "["+k+"]")
		g := groups[k]
		sort.SliceStable(g, func(i, j int) bool { return g[i].Name < g[j].Name })
		for _, c := range g {
			first := strings.TrimSpace(c.Description)
			if i := strings.IndexAny(first, "\r\n"); i >= 0 {
				first = first[:i]
			}
			if first != "" {
				lines = append(lines, fmt.Sprintf("- %s: %s", c.Name, first))
			} else {
				lines = append(lines, "- "+c.Name)
			}
		}
	}
	return strings.Join(lines, "\n")
}

// RevealResult is what load_tools reveals of the searchable pool.
type RevealResult struct {
	Revealed []map[string]any
	Matched  []string
	Unknown  []string
	Message  string
}

// RevealTools is NamedLookupPolicy.reveal.
func RevealTools(names []string, pool []api.SearchableTool) RevealResult {
	index := map[string]api.SearchableTool{}
	for _, c := range pool {
		index[c.Name] = c
	}
	var r RevealResult
	for _, n := range names {
		c, ok := index[n]
		if !ok {
			r.Unknown = append(r.Unknown, n)
			continue
		}
		r.Revealed = append(r.Revealed, c.Schema)
		r.Matched = append(r.Matched, n)
	}
	if len(r.Unknown) > 0 {
		valid := make([]string, 0, len(index))
		for k := range index {
			valid = append(valid, k)
		}
		sort.Strings(valid)
		more := ""
		if len(index) > 20 {
			more = " (more available)"
		}
		r.Message = fmt.Sprintf("Loaded %d of %d requested operations. Unknown names: %s. Valid examples: %s%s",
			len(r.Matched), len(names), PyListRepr(r.Unknown), PyListRepr(valid[:min(20, len(valid))]), more)
	} else {
		r.Message = fmt.Sprintf("Loaded %d operations: %s", len(r.Matched), PyListRepr(r.Matched))
	}
	return r
}

// PyListRepr renders a string list the way Python's repr does.
func PyListRepr(items []string) string {
	parts := make([]string, len(items))
	for i, s := range items {
		if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
			parts[i] = `"` + s + `"`
		} else {
			parts[i] = "'" + strings.ReplaceAll(strings.ReplaceAll(s, `\`, `\\`), "'", `\'`) + "'"
		}
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}
