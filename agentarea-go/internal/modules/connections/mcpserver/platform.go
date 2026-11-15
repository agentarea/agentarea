package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"slices"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/mcpserve"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
)

// WorkspaceArgument is the argument a spanning mount's workspace-scoped tools take.
const WorkspaceArgument = "workspace"

const workspaceProperty = (`{"description":"Slug or id of the workspace to act in.","title":"Workspace","type":"string"}`)

// Namespaced is a toolset that also answers to a namespace in ?toolsets=.
type Namespaced interface{ Namespace() string }

// Unscoped is a toolset that acts on no single workspace: on the spanning
// mount its tools take no workspace argument.
type Unscoped interface{ Unscoped() bool }

// Platform is the platform MCP server (platform_mcp.create_platform_mcp_server):
// every registered toolset, spanning the caller's workspaces or pinned to one.
type Platform struct {
	spanning bool
	info     Info
	auth     Auth
	toolsets []mcpserve.Toolset
	log      *slog.Logger
}

var _ mcpserve.Server = (*Platform)(nil)

// NewPlatform builds the spanning (/mcp) or pinned (/mcp/w/{workspace}) server.
func NewPlatform(spanning bool, info Info, auth Auth, log *slog.Logger) *Platform {
	if log == nil {
		log = slog.New(slog.DiscardHandler)
	}
	return &Platform{spanning: spanning, info: info, auth: auth, log: log}
}

// Register adds toolsets, in the order tools/list shows them. A pinned
// server leaves out a toolset that acts on no single workspace.
func (p *Platform) Register(ts ...mcpserve.Toolset) {
	for _, t := range ts {
		if u, ok := t.(Unscoped); ok && u.Unscoped() && !p.spanning {
			continue
		}
		p.toolsets = append(p.toolsets, t)
	}
}

// Toolsets are the registered toolsets' names.
func (p *Platform) Toolsets() []string {
	names := make([]string, 0, len(p.toolsets))
	for _, t := range p.toolsets {
		names = append(names, t.Name())
	}
	return names
}

// Handler serves mount: MountSpan, or MountPinned with the workspace in the
// chi route parameter "workspace".
func (p *Platform) Handler(mount string) http.Handler {
	endpoint := &Endpoint{Info: p.info, Log: p.log, Backend: p.backend}
	prefix := strings.Trim(strings.TrimSuffix(mount, "/{workspace}"), "/")
	authed := p.auth.Wrap(endpoint, func(r *http.Request) Mount {
		if !p.pinned(mount) {
			return Mount{}
		}
		ws := chi.URLParam(r, "workspace")
		return Mount{Resource: prefix + "/" + ws, Workspace: ws}
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if p.pinned(mount) && !ValidWorkspaceReference(chi.URLParam(r, "workspace")) {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		sel, err := p.selection(r)
		if err != nil {
			WriteError(w, http.StatusBadRequest, nil, &Error{Code: CodeInvalidParams, Message: err.Error()})
			return
		}
		authed.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), selectionKey{}, sel)))
	})
}

func (p *Platform) pinned(mount string) bool { return strings.Contains(mount, "{workspace}") }

type selectionKey struct{}

// selection is ToolsetSelectionMiddleware: ?toolsets= names toolsets by name
// or namespace; nil serves every toolset, an unknown name is refused.
func (p *Platform) selection(r *http.Request) ([]mcpserve.Toolset, error) {
	values, ok := r.URL.Query()[ToolsetsParam]
	if !ok {
		return nil, nil
	}
	var names []string
	for _, v := range values {
		for _, n := range strings.Split(v, ",") {
			if n = strings.TrimSpace(n); n != "" {
				names = append(names, n)
			}
		}
	}
	available := strings.Join(p.Toolsets(), ", ")
	if len(names) == 0 {
		return nil, errors.New("'" + ToolsetsParam + "' names no toolset. Available: " + available)
	}
	var out []mcpserve.Toolset
	for _, n := range names {
		t := p.resolve(n)
		if t == nil {
			return nil, errors.New("Unknown toolset '" + n + "'. Available: " + available)
		}
		if !slices.Contains(out, t) {
			out = append(out, t)
		}
	}
	return out, nil
}

// ToolsetsParam is the query parameter that narrows a platform mount.
const ToolsetsParam = "toolsets"

func (p *Platform) resolve(ref string) mcpserve.Toolset {
	for _, t := range p.toolsets {
		if t.Name() == ref {
			return t
		}
		if ns, ok := t.(Namespaced); ok && ns.Namespace() == ref {
			return t
		}
	}
	return nil
}

func (p *Platform) backend(r *http.Request) (Backend, error) {
	prin, ok := authn.PrincipalFrom(r.Context())
	if !ok {
		return nil, authn.ErrNoPrincipal
	}
	served := p.toolsets
	if sel, _ := r.Context().Value(selectionKey{}).([]mcpserve.Toolset); sel != nil {
		served = sel
	}
	return &platformBackend{p: p, principal: prin, served: served}, nil
}

type platformBackend struct {
	p         *Platform
	principal authn.Principal
	served    []mcpserve.Toolset
}

func (p *Platform) scoped(t mcpserve.Toolset) bool {
	if u, ok := t.(Unscoped); ok && u.Unscoped() {
		return false
	}
	return p.spanning
}

func (b *platformBackend) ListTools(ctx context.Context) ([]Tool, error) {
	var out []Tool
	for _, t := range b.served {
		tools, err := t.Tools(ctx, b.principal)
		if err != nil {
			return nil, err
		}
		for _, tool := range tools {
			if b.p.scoped(t) {
				schema, err := withWorkspaceArgument(tool.InputSchema)
				if err != nil {
					return nil, err
				}
				tool.InputSchema = schema
			}
			out = append(out, Tool{Tool: tool})
		}
	}
	return out, nil
}

func (b *platformBackend) owner(name string) mcpserve.Toolset {
	var best mcpserve.Toolset
	for _, t := range b.served {
		if strings.HasPrefix(name, t.Name()+"_") && (best == nil || len(t.Name()) > len(best.Name())) {
			best = t
		}
	}
	return best
}

func (b *platformBackend) CallTool(ctx context.Context, name string, args json.RawMessage) (any, error) {
	t := b.owner(name)
	if t == nil {
		return errorResult("Unknown tool: " + name), nil
	}
	if b.p.scoped(t) {
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(args, &fields); err != nil {
			return nil, &Error{Code: CodeInvalidParams, Message: "Invalid request parameters"}
		}
		var ref string
		if raw, ok := fields[WorkspaceArgument]; !ok || json.Unmarshal(raw, &ref) != nil || ref == "" {
			return errorResult("Missing required argument '" + WorkspaceArgument + "' for tool " + name), nil
		}
		c, err := b.p.auth.Gate.EnterWorkspace(ctx, b.principal, ref)
		if err != nil {
			var unreachable *scope.UnreachableError
			if errors.As(err, &unreachable) {
				return errorResult("No accessible workspace '" + ref + "'"), nil
			}
			return nil, err
		}
		delete(fields, WorkspaceArgument)
		stripped, err := json.Marshal(fields)
		if err != nil {
			return nil, err
		}
		args = stripped
		ctx = authn.WithCaller(ctx, c)
	}
	res, err := t.Call(ctx, b.principal, name, args)
	if err != nil {
		b.p.log.WarnContext(ctx, "Platform tool failed", "tool", name, "error", err)
		return errorResult(err.Error()), nil
	}
	if res.Content == nil {
		res.Content = []mcpserve.Content{}
	}
	return res, nil
}

func errorResult(text string) mcpserve.Result {
	return mcpserve.Result{Content: []mcpserve.Content{{Type: "text", Text: text}}, IsError: true}
}

// withWorkspaceArgument puts the required workspace argument first, as the
// spanning mount's contract lists it.
func withWorkspaceArgument(schema json.RawMessage) (json.RawMessage, error) {
	var top map[string]json.RawMessage
	if err := json.Unmarshal(schema, &top); err != nil {
		return nil, err
	}
	props := []byte(strings.TrimSpace(string(top["properties"])))
	if len(props) < 2 || props[0] != '{' {
		props = []byte("{}")
	}
	inner := strings.TrimSpace(string(props[1 : len(props)-1]))
	merged := `{"` + WorkspaceArgument + `":` + workspaceProperty
	if inner != "" {
		merged += "," + inner
	}
	top["properties"] = json.RawMessage(merged + "}")
	var required []string
	if raw, ok := top["required"]; ok {
		if err := json.Unmarshal(raw, &required); err != nil {
			return nil, err
		}
	}
	required = append([]string{WorkspaceArgument}, required...)
	rawRequired, err := json.Marshal(required)
	if err != nil {
		return nil, err
	}
	top["required"] = rawRequired
	return json.Marshal(top)
}

// Carried is _platform_tools: the tools of a client's attached toolsets,
// minus their disabled methods, listed as c in c's workspace. A toolset the
// platform no longer serves is skipped, loudly.
func (p *Platform) Carried(ctx context.Context, c authn.Caller, attached []agentsapi.ClientToolset) ([]Tool, error) {
	ctx = authn.WithCaller(ctx, c)
	var out []Tool
	for _, a := range attached {
		t := p.resolve(a.Toolset)
		if t == nil {
			p.log.ErrorContext(ctx, "Client carries a platform toolset that is no longer served", "toolset", a.Toolset)
			continue
		}
		tools, err := t.Tools(ctx, c.Principal)
		if err != nil {
			return nil, err
		}
		for _, tool := range tools {
			method := strings.TrimPrefix(tool.Name, t.Name()+"_")
			if !slices.Contains(a.DisabledMethods, method) {
				out = append(out, Tool{Tool: tool})
			}
		}
	}
	return out, nil
}

// CallCarried runs one platform tool as c in c's workspace, as on /mcp/w/{workspace}.
func (p *Platform) CallCarried(ctx context.Context, c authn.Caller, name string, args json.RawMessage) (any, error) {
	b := &platformBackend{p: p, principal: c.Principal, served: p.toolsets}
	return b.CallTool(authn.WithCaller(ctx, c), name, args)
}

// Serves reports whether the registered toolset named toolset has method.
func (p *Platform) Serves(toolset, method string) bool {
	for _, t := range p.toolsets {
		if t.Name() != toolset {
			continue
		}
		tools, err := t.Tools(context.Background(), authn.Principal{})
		if err != nil {
			return false
		}
		return slices.ContainsFunc(tools, func(tool mcpserve.Tool) bool { return tool.Name == toolset+"_"+method })
	}
	return false
}

// Run is CallCarried's tool result: a failed call is a result with IsError.
func (p *Platform) Run(ctx context.Context, c authn.Caller, name string, args json.RawMessage) (mcpserve.Result, error) {
	out, err := p.CallCarried(ctx, c, name, args)
	if err != nil {
		return mcpserve.Result{}, err
	}
	res, ok := out.(mcpserve.Result)
	if !ok {
		return mcpserve.Result{}, fmt.Errorf("platform tool %s answered %T", name, out)
	}
	return res, nil
}
