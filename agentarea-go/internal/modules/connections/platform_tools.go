package connections

import (
	"context"
	"errors"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/mcpserver"
)

// PlatformTools runs the platform toolsets for runs (code tools of a
// platform namespace), over the same registry /mcp/w/{workspace} serves.
func (m *Module) PlatformTools() api.PlatformTools { return platformTools{m} }

type platformTools struct{ m *Module }

func (t platformTools) Call(ctx context.Context, call api.PlatformCall) (api.PlatformResult, error) {
	name, ok := strings.CutPrefix(call.Namespace, "agentarea/")
	if !ok || call.Method == "" {
		return api.PlatformResult{}, api.ErrUnknownPlatformTool
	}
	if call.UserID == "" || call.AgentID == "" {
		return api.PlatformResult{}, errors.New("a platform tool call from a run needs its user and agent")
	}
	providers := t.m.providers()
	slug := ""
	if providers.Slugs != nil {
		var err error
		if slug, err = providers.Slugs.Slug(ctx, call.WorkspaceID); err != nil {
			return api.PlatformResult{}, err
		}
	}
	ws, err := scope.NewWorkspace(call.WorkspaceID, slug)
	if err != nil {
		return api.PlatformResult{}, err
	}
	toolsets, err := providers.Toolsets(t.m.d.APIURL)
	if err != nil {
		return api.PlatformResult{}, err
	}
	p := mcpserver.NewPlatform(false, mcpserver.Info{}, mcpserver.Auth{}, t.m.d.Log)
	p.Register(toolsets...)
	if !p.Serves(name, call.Method) {
		return api.PlatformResult{}, api.ErrUnknownPlatformTool
	}
	c := authn.Caller{Principal: authn.Principal{
		UserID: call.UserID, Subject: &authn.Subject{Kind: authn.SubjectAgent, ID: call.AgentID},
		AccessibleWorkspaces: []string{call.WorkspaceID},
	}, Workspace: ws}
	args := call.Args
	if len(args) == 0 {
		args = []byte(`{}`)
	}
	res, err := p.Run(ctx, c, name+"_"+call.Method, args)
	if err != nil {
		return api.PlatformResult{}, err
	}
	text := ""
	for _, part := range res.Content {
		text += part.Text
	}
	return api.PlatformResult{Text: text, IsError: res.IsError, StructuredContent: res.StructuredContent}, nil
}
