// Package mcpbase names the runtime that serves `command` connections: the
// mcp-base image runs the connection's stdio command (`npx -y <pkg>`,
// `uvx <pkg>`) behind its bridge and serves Streamable HTTP on Port at /mcp.
//
// It is its own package so the Docker launch path (internal/container) and the
// provider path (internal/providers) read one definition; the two cannot import
// each other.
package mcpbase

import "os"

// Port is where the mcp-base bridge listens. It opens only after the stdio
// server has initialized.
const Port = 8080

// DefaultImage is used when AGENTAREA_MCP_BASE_IMAGE is unset. Deployments pin a
// version through AGENTAREA_MCP_BASE_IMAGE (chart value mcpManager.mcpBase.image).
const DefaultImage = "agentarea/agentarea-mcp-base:latest"

// Image returns the configured mcp-base image reference.
func Image() string {
	if image := os.Getenv("AGENTAREA_MCP_BASE_IMAGE"); image != "" {
		return image
	}
	return DefaultImage
}
