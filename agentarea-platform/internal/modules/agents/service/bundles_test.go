package service

import (
	"context"
	"reflect"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

func TestBundleToolsAfterKeepsDelegateSettingsAndMovesTheAgentID(t *testing.T) {
	old, fresh, kept := "agent-old", "agent-new", "agent-ui"
	confirm, override := true, "Hand finished drafts to the writer"
	allowed := []domain.MCPPermission{{ToolName: "send"}}
	current := []domain.Tool{
		{Type: domain.ToolMCP, Name: "mcp-1", Settings: &domain.Settings{MCPAllowed: &allowed}},
		{Type: domain.ToolAgent, Name: "writer", Settings: &domain.Settings{AgentID: &old, RequiresUserConfirmation: &confirm, DescriptionOverride: &override}},
		{Type: domain.ToolAgent, Name: "editor", Settings: &domain.Settings{AgentID: &old}},
		{Type: domain.ToolAgent, Name: "helper", Settings: &domain.Settings{AgentID: &kept}},
	}
	got := bundleToolsAfter(current, catalogapi.BundleAgentUpdate{
		Tools:        []catalogapi.BundleTool{{Type: "mcp", Name: "mcp-1"}, {Type: "agent", Name: "writer", AgentID: &fresh}},
		ManagedTools: []catalogapi.BundleTool{{Type: "mcp", Name: "mcp-1"}, {Type: "agent", Name: "writer"}, {Type: "agent", Name: "editor"}},
	})
	want := []domain.Tool{
		current[0],
		{Type: domain.ToolAgent, Name: "writer", Settings: &domain.Settings{AgentID: &fresh, RequiresUserConfirmation: &confirm, DescriptionOverride: &override}},
		current[3],
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("tools = %+v", got)
	}
	if *current[1].Settings.AgentID != old {
		t.Fatal("the current tool's settings were written through")
	}
}

// A delegate whose key was renamed is the same agent: its tool takes the new name and keeps its settings.
func TestBundleToolsAfterRenamesADelegateByItsAgentID(t *testing.T) {
	b := "agent-b"
	confirm := true
	current := []domain.Tool{{Type: domain.ToolAgent, Name: "b", Settings: &domain.Settings{AgentID: &b, RequiresUserConfirmation: &confirm}}}
	got := bundleToolsAfter(current, catalogapi.BundleAgentUpdate{
		Tools:        []catalogapi.BundleTool{{Type: "agent", Name: "c", AgentID: &b}},
		ManagedTools: []catalogapi.BundleTool{{Type: "agent", Name: "c", AgentID: &b}},
	})
	want := []domain.Tool{{Type: domain.ToolAgent, Name: "c", Settings: &domain.Settings{AgentID: &b, RequiresUserConfirmation: &confirm}}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("tools = %+v", got)
	}
}

func TestBundleOpenAPIToolNamesItsConnection(t *testing.T) {
	id := "conn-1"
	got := bundleTool(catalogapi.BundleTool{Type: "openapi", Name: id, ConnectionID: &id})
	if got.Type != domain.ToolOpenAPI || got.Name != id || got.Settings == nil || got.Settings.OpenAPIConnectionID == nil ||
		*got.Settings.OpenAPIConnectionID != id {
		t.Fatalf("tool = %+v", got)
	}
	added := bundleToolsAfter(nil, catalogapi.BundleAgentUpdate{Tools: []catalogapi.BundleTool{{Type: "openapi", Name: id, ConnectionID: &id}}})
	if len(added) != 1 || added[0].Settings == nil || *added[0].Settings.OpenAPIConnectionID != id {
		t.Fatalf("added = %+v", added)
	}
}

// A code toolset the folder declares takes the folder's models; its other settings stay.
func TestBundleToolsAfterTakesTheFolderModelsOfACodeToolset(t *testing.T) {
	old, fresh, video := "image-old", "image-new", "video-1"
	confirm := true
	current := []domain.Tool{
		{Type: domain.ToolCode, Name: "agentarea/media", Settings: &domain.Settings{ImageModelID: &old, VideoModelID: &video, RequiresUserConfirmation: &confirm}},
		{Type: domain.ToolCode, Name: "agentarea/files"},
	}
	declared := []catalogapi.BundleTool{{Type: "code", Name: "agentarea/media", ImageModelID: &fresh}, {Type: "code", Name: "agentarea/files"}}
	got := bundleToolsAfter(current, catalogapi.BundleAgentUpdate{Tools: declared, ManagedTools: declared})
	want := []domain.Tool{
		{Type: domain.ToolCode, Name: "agentarea/media", Settings: &domain.Settings{ImageModelID: &fresh, RequiresUserConfirmation: &confirm}},
		{Type: domain.ToolCode, Name: "agentarea/files"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("tools = %+v", got)
	}
	if *current[0].Settings.ImageModelID != old {
		t.Fatal("the current tool's settings were written through")
	}
	added := bundleTool(declared[0])
	if added.Settings == nil || *added.Settings.ImageModelID != fresh || added.Settings.VideoModelID != nil {
		t.Fatalf("added = %+v", added)
	}
}

type bundleFakeModels map[string]string

func (m bundleFakeModels) ModelKind(_ context.Context, _ scope.Workspace, id string) (string, bool, error) {
	k, ok := m[id]
	return k, ok, nil
}

func (m bundleFakeModels) InstanceName(_ context.Context, _ scope.Workspace, id string) (modelsapi.InstanceName, bool, error) {
	k, ok := m[id]
	return modelsapi.InstanceName{ID: id, Kind: k}, ok, nil
}

type bundleFakeCodeTools []string

func (n bundleFakeCodeTools) Names() []string       { return n }
func (bundleFakeCodeTools) Metadata() []CodeToolset { return nil }

func TestBundleAgentProblemChecksToolsetModels(t *testing.T) {
	image, video := uuid.NewString(), uuid.NewString()
	b := BundleAgents{K: &Skills{s: New(Deps{Models: bundleFakeModels{image: "image", video: "video"},
		CodeTools: bundleFakeCodeTools{"agentarea/media", "agentarea/files"}})}}
	for _, tc := range []struct {
		tool catalogapi.BundleTool
		want string
	}{
		{catalogapi.BundleTool{Type: "code", Name: "agentarea/media", ImageModelID: &image}, ""},
		{catalogapi.BundleTool{Type: "code", Name: "agentarea/media", VideoModelID: &video}, ""},
		{catalogapi.BundleTool{Type: "code", Name: "agentarea/media"}, "Tool 'agentarea/media' needs an image_model_id or a video_model_id."},
		{catalogapi.BundleTool{Type: "code", Name: "agentarea/media", ImageModelID: &video},
			"Model instance '" + video + "' is a video model; image_model_id of 'agentarea/media' must be a image model."},
		{catalogapi.BundleTool{Type: "code", Name: "agentarea/files", ImageModelID: &image}, "Tool 'agentarea/files' takes no image_model_id."},
	} {
		got, err := b.AgentProblem(context.Background(), authn.Caller{}, catalogapi.BundleAgentConfig{Toolsets: []catalogapi.BundleTool{tc.tool}})
		if err != nil || got != tc.want {
			t.Errorf("%+v: problem = %q, %v; want %q", tc.tool, got, err, tc.want)
		}
	}
}
