package contract

import (
	_ "embed"
	"strings"
)

//go:embed tools-pending.txt
var toolsPendingTxt string

//go:embed tools-added.txt
var toolsAddedTxt string

// ToolsPending are the contract's platform MCP tools Go does not serve yet,
// one name per line of tools-pending.txt; the list only shrinks.
func ToolsPending() []string {
	var out []string
	for _, line := range strings.Split(toolsPendingTxt, "\n") {
		if line = strings.TrimSpace(line); line != "" && !strings.HasPrefix(line, "#") {
			out = append(out, line)
		}
	}
	return out
}

// ToolsAdded are the platform MCP tools Go serves that the contract does not
// list, each with its reason: "name reason" per line of tools-added.txt.
func ToolsAdded() map[string]string {
	out := map[string]string{}
	for _, line := range strings.Split(toolsAddedTxt, "\n") {
		if line = strings.TrimSpace(line); line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		name, reason, _ := strings.Cut(line, " ")
		out[name] = strings.TrimSpace(reason)
	}
	return out
}
