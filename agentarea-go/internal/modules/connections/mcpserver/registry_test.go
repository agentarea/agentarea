package mcpserver

import (
	"context"
	"encoding/json"
	"slices"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/api/contract"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/mcpserve"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	insightsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	projectsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// everyProvider sets every provider; the registry test lists tools and calls none.
func everyProvider() Providers {
	return Providers{
		Agents: struct{ agentsapi.Agents }{}, Runs: struct{ runsapi.PlatformRuns }{}, TaskDefs: struct{ agentsapi.TaskDefs }{},
		Skills: struct{ agentsapi.Skills }{}, Projects: struct{ projectsapi.PlatformProjects }{}, Clients: struct{ agentsapi.Clients }{},
		Members: struct{ identityapi.Members }{}, Policies: struct{ governanceapi.PlatformPolicies }{},
		Triggers: struct{ streamsapi.PlatformTriggers }{}, Streams: struct{ streamsapi.PlatformStreams }{},
		StreamEvents: struct {
			streamsapi.PlatformStreamEvents
		}{}, WorkspaceFiles: struct{ sandboxapi.PlatformFiles }{},
		Inbox: struct{ runsapi.PlatformInbox }{}, OpenAPI: struct{ connectionsapi.PlatformOpenAPI }{},
		MCPServers: struct {
			connectionsapi.PlatformMCPServers
		}{}, ConnectorTools: struct {
			connectionsapi.PlatformConnectorTools
		}{},
		LLMProviders: struct{ modelsapi.PlatformProviders }{}, Models: struct{ modelsapi.PlatformModels }{},
		Secrets: struct{ governanceapi.PlatformSecrets }{}, Audit: struct{ governanceapi.PlatformAudit }{},
		Network: struct{ insightsapi.PlatformNetwork }{}, WorkspaceConfig: struct{ agentsapi.WorkspaceConfig }{},
		Files: struct{ sandboxapi.Files }{},
	}
}

type servedTool struct {
	toolset  string
	props    []string
	required []string
}

// registryTools is what a mount lists with every provider set, by tool name.
func registryTools(t *testing.T, spanning bool) map[string]servedTool {
	t.Helper()
	c, err := loadContract()
	if err != nil {
		t.Fatal(err)
	}
	p := NewPlatform(spanning, Info{}, Auth{}, nil)
	for _, s := range everyProvider().specs("https://api.example") {
		defs := s.defs()
		if len(defs) == 0 {
			continue
		}
		server := c.PlatformPinned
		if s.unscoped {
			server = c.PlatformSpanning
		}
		ts, err := newContractToolset(server, s.Name, "agentarea/"+s.Name, defs)
		if err != nil {
			t.Fatal(err)
		}
		ts.unscoped = s.unscoped
		p.Register(ts)
	}
	out := map[string]servedTool{}
	for _, ts := range p.toolsets {
		b := &platformBackend{p: p, served: []mcpserve.Toolset{ts}}
		tools, err := b.ListTools(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		for _, tool := range tools {
			if _, dup := out[tool.Name]; dup {
				t.Fatalf("%s is served twice", tool.Name)
			}
			props, required := schemaKeys(t, tool.Name, tool.InputSchema)
			out[tool.Name] = servedTool{toolset: ts.Name(), props: props, required: required}
		}
	}
	return out
}

func schemaKeys(t *testing.T, name string, schema json.RawMessage) ([]string, []string) {
	t.Helper()
	var s struct {
		Properties map[string]json.RawMessage `json:"properties"`
		Required   []string                   `json:"required"`
	}
	if err := json.Unmarshal(schema, &s); err != nil {
		t.Fatalf("%s schema: %v", name, err)
	}
	props := make([]string, 0, len(s.Properties))
	for k := range s.Properties {
		props = append(props, k)
	}
	slices.Sort(props)
	return props, s.Required
}

// TestRegistryMatchesContract compares the platform tool registry with
// mcp-tools.json on both mounts. A contract tool Go does not serve must be
// listed in tools-pending.txt, a listed one that is served must leave it,
// and a Go tool the contract lacks must be in tools-added.txt.
func TestRegistryMatchesContract(t *testing.T) {
	c, err := contract.LoadMCPTools()
	if err != nil {
		t.Fatal(err)
	}
	pending := map[string]bool{}
	for _, name := range contract.ToolsPending() {
		if pending[name] {
			t.Errorf("tools-pending.txt lists %s twice", name)
		}
		pending[name] = true
	}
	added := contract.ToolsAdded()
	for name, reason := range added {
		if reason == "" {
			t.Errorf("tools-added.txt gives no reason for %s", name)
		}
	}
	listed := map[string]bool{}
	for _, mount := range []struct {
		server   contract.MCPServer
		spanning bool
		count    int
	}{{c.PlatformSpanning, true, 137}, {c.PlatformPinned, false, 134}} {
		if len(mount.server.Tools) != mount.count {
			t.Fatalf("%s: contract lists %d tools, want %d", mount.server.Mount, len(mount.server.Tools), mount.count)
		}
		served := registryTools(t, mount.spanning)
		inContract := map[string]bool{}
		for _, want := range mount.server.Tools {
			inContract[want.Name] = true
			listed[want.Name] = true
			got, ok := served[want.Name]
			if !ok {
				if !pending[want.Name] {
					t.Errorf("%s: %s is not served and not in tools-pending.txt", mount.server.Mount, want.Name)
				}
				continue
			}
			if pending[want.Name] {
				t.Errorf("%s: %s is served; remove it from tools-pending.txt", mount.server.Mount, want.Name)
			}
			props, required := schemaKeys(t, want.Name, want.InputSchema)
			if got.toolset != want.Toolset {
				t.Errorf("%s: %s is in toolset %s, contract says %s", mount.server.Mount, want.Name, got.toolset, want.Toolset)
			}
			if !slices.Equal(got.props, props) {
				t.Errorf("%s: %s properties %v, contract %v", mount.server.Mount, want.Name, got.props, props)
			}
			if !slices.Equal(got.required, required) {
				t.Errorf("%s: %s required %v, contract %v", mount.server.Mount, want.Name, got.required, required)
			}
		}
		for name := range served {
			if !inContract[name] && added[name] == "" {
				t.Errorf("%s: %s is served but not in the contract nor tools-added.txt", mount.server.Mount, name)
			}
		}
	}
	for name := range pending {
		if !listed[name] {
			t.Errorf("tools-pending.txt lists %s, which the contract does not", name)
		}
	}
}
