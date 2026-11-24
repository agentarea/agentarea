package mcpserver

import (
	"runtime/debug"
	"strings"
)

// Platform identity (platform_mcp.server_identity).
const (
	PlatformName         = "AgentArea"
	PlatformInstructions = "AgentArea platform — agents, runs, MCP servers, providers, models, secrets"
	platformTitle        = "AgentArea"
	platformDescription  = "Build, run and govern AI agents on AgentArea: create agents and skills, start and " +
		"steer runs, connect MCP servers and OpenAPI tools, wire triggers and event streams, " +
		"and manage providers, models, secrets, members and policies across your workspaces."
	platformWebsite = "https://docs.agentarea.ai"
)

// Identity is what every AgentArea MCP endpoint reports about itself, under
// its own name and instructions.
func Identity(apiURL, name, instructions string) Info {
	version := "(unknown)"
	if bi, ok := debug.ReadBuildInfo(); ok {
		version = strings.TrimPrefix(bi.Main.Version, "v")
	}
	return Info{
		Name: name, Title: platformTitle, Description: platformDescription, Version: version,
		WebsiteURL: platformWebsite, Instructions: instructions,
		Icons: []Icon{{Src: strings.TrimRight(apiURL, "/") + "/static/icons/agentarea.svg", MimeType: "image/svg+xml", Sizes: []string{"any"}}},
	}
}
