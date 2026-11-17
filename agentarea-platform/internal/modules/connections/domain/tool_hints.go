package domain

// ToolSafetyHint is _tool_safety_hint: "destructive" or "read-only" from a
// stored MCP tool's annotations, destructive winning; both the camelCase and
// the older snake_case spellings are read. Empty when neither is set.
func ToolSafetyHint(tool map[string]any) string {
	ann, _ := tool["annotations"].(map[string]any)
	switch {
	case Truthy(ann["destructiveHint"]) || Truthy(ann["destructive_hint"]):
		return "destructive"
	case Truthy(ann["readOnlyHint"]) || Truthy(ann["read_only_hint"]):
		return "read-only"
	}
	return ""
}

// ToolMaps are the stored tools that are objects.
func ToolMaps(tools []any) []map[string]any {
	out := make([]map[string]any, 0, len(tools))
	for _, t := range tools {
		if m, ok := t.(map[string]any); ok {
			out = append(out, m)
		}
	}
	return out
}
