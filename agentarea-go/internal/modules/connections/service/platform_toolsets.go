package service

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/mcpclient"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/toolname"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// allConnections are the connections the workspace sees matching f, newest first.
func (s *Service) allConnections(ctx context.Context, c authn.Caller, f ConnectionFilter) ([]domain.Connection, error) {
	var rows []domain.Connection
	err := s.read(ctx, c, func(sess db.Session) (err error) {
		rows, err = s.d.Connections.List(ctx, sess, f, math.MaxInt32, 0)
		return err
	})
	return rows, err
}

// ConnectionsPage is list_connections: the page [offset, offset+limit) of
// the connections whose name or description holds search, and their total.
func (s *Service) ConnectionsPage(ctx context.Context, c authn.Caller, search string, limit, offset int) ([]ConnectionView, int, error) {
	var f ConnectionFilter
	if search != "" {
		p := "%" + search + "%"
		f.Pattern = &p
	}
	rows, err := s.allConnections(ctx, c, f)
	if err != nil {
		return nil, 0, err
	}
	offset = min(max(offset, 0), len(rows))
	page := rows[offset:min(offset+max(limit, 0), len(rows))]
	views, err := s.views(ctx, c, page)
	return views, len(rows), err
}

// ConnectPageURL is connect_page_url: the page a person opens to connect id.
func (s *Service) ConnectPageURL(slug, id string) (string, error) {
	if strings.TrimRight(s.d.AppURL, "/") == "" {
		return "", errors.New("AGENTAREA_APP_URL is not set: a connect link has no page to point at")
	}
	return s.connectPageURL(slug, id), nil
}

// NeedsConnecting is needs_connecting: the instance waits on a credential
// only a person can give it. With probe, a URL instance holding no
// credential is asked whether it wants authorization, and an upstream that
// does is recorded as auth_required.
func (s *Service) NeedsConnecting(ctx context.Context, c authn.Caller, inst domain.Instance, probe bool) (bool, error) {
	v := inst.Verification
	if v.Status == domain.VerifySucceeded || inst.Transport == domain.TransportBundle {
		return false, nil
	}
	if v.Error != nil && v.Error.Code == CodeOAuthReauthRequired {
		return true, nil
	}
	if isAuthFailure(v) {
		return true, nil
	}
	if inst.AuthConfigID != nil && *inst.AuthConfigID != "" {
		return false, nil
	}
	schema, err := s.envSchema(ctx, c.Workspace, inst, nil)
	if err != nil {
		return false, err
	}
	var required []string
	for _, f := range schema {
		if f.IsSecret && f.IsRequired {
			required = append(required, f.Name)
		}
	}
	if len(required) > 0 {
		values, err := s.instanceSecrets(ctx, inst, required)
		if err != nil {
			return false, err
		}
		for _, n := range required {
			if values[n] == "" {
				return true, nil
			}
		}
	}
	recorded := v.Error != nil && v.Error.Code == CodeAuthRequired
	if !probe && !recorded || v.Status == domain.VerifyInProgress || inst.Transport != domain.TransportURL {
		return false, nil
	}
	values, err := s.instanceSecrets(ctx, inst, inst.EnvVars())
	if err != nil {
		return false, err
	}
	for _, val := range values {
		if val != "" {
			return false, nil
		}
	}
	if recorded {
		return true, nil
	}
	id := uuid.MustParse(inst.ID)
	r, err := s.Probe(ctx, c.Workspace, id)
	var refused *domain.Invalid
	if errors.As(err, &refused) {
		s.d.Log.InfoContext(ctx, "Auth probe refused", "instance_id", inst.ID, "reason", refused.Msg)
		return false, nil
	}
	if err != nil || r.Status != "auth_required" {
		return false, err
	}
	methods := make([]any, len(r.Methods))
	for i, m := range r.Methods {
		methods[i] = m
	}
	_, err = s.store(ctx, c.Workspace, id, s.payload(domain.VerifyFailed,
		failure(CodeAuthRequired, inst.Name+" requires sign-in or a key", map[string]any{"methods": methods})))
	return true, err
}

// catalogConnection is one of the caller's connections from a catalog item, with its age.
type catalogConnection struct {
	api.CatalogConnection
	created time.Time
}

// OtherCatalogConnections is other_catalog_connections: the caller's
// readable connections made from the catalog item, exclude left out,
// oldest first.
func (s *Service) OtherCatalogConnections(ctx context.Context, c authn.Caller, itemID, exclude string) ([]api.CatalogConnection, error) {
	found, err := s.catalogConnections(ctx, c, []string{itemID}, exclude)
	return found[itemID], err
}

// CatalogConnections is readable_catalog_connections: per catalog item, the
// caller's readable connections made from it, oldest first. Items without
// any are absent.
func (s *Service) CatalogConnections(ctx context.Context, c authn.Caller, itemIDs []string) (map[string][]api.CatalogConnection, error) {
	return s.catalogConnections(ctx, c, itemIDs, "")
}

func (s *Service) catalogConnections(ctx context.Context, c authn.Caller, itemIDs []string, exclude string) (map[string][]api.CatalogConnection, error) {
	wanted := map[string]bool{}
	for _, id := range itemIDs {
		wanted[id] = true
	}
	if len(wanted) == 0 {
		return map[string][]api.CatalogConnection{}, nil
	}
	readable, err := s.ReadableIDs(ctx, c)
	if err != nil || len(readable) == 0 {
		return map[string][]api.CatalogConnection{}, err
	}
	var instances []domain.Instance
	err = s.read(ctx, c, func(sess db.Session) (err error) {
		instances, err = s.d.Instances.List(ctx, sess)
		return err
	})
	if err != nil {
		return nil, err
	}
	found := map[string][]catalogConnection{}
	items := map[string]string{}
	for _, inst := range instances {
		if _, ok := readable[inst.ID]; !ok || inst.WorkspaceID != c.Workspace.ID() || inst.ID == exclude || inst.ServerSpecID == "" {
			continue
		}
		item, seen := items[inst.ServerSpecID]
		if !seen {
			if item, err = s.specRegistryItem(ctx, c, inst); err != nil {
				return nil, err
			}
			items[inst.ServerSpecID] = item
		}
		if wanted[item] {
			found[item] = append(found[item], catalogConnection{api.CatalogConnection{ID: inst.ID, Kind: "mcp", Name: inst.Name}, inst.CreatedAt})
		}
	}
	conns, err := s.allConnections(ctx, c, ConnectionFilter{})
	if err != nil {
		return nil, err
	}
	for _, conn := range conns {
		if _, ok := readable[conn.ID]; !ok || conn.WorkspaceID != c.Workspace.ID() || conn.ID == exclude ||
			conn.RegistryItemID == nil || !wanted[*conn.RegistryItemID] {
			continue
		}
		item := *conn.RegistryItemID
		found[item] = append(found[item], catalogConnection{api.CatalogConnection{ID: conn.ID, Kind: "openapi", Name: conn.Name}, conn.CreatedAt})
	}
	out := make(map[string][]api.CatalogConnection, len(found))
	for item, list := range found {
		sort.SliceStable(list, func(i, j int) bool {
			if !list[i].created.Equal(list[j].created) {
				return list[i].created.Before(list[j].created)
			}
			return list[i].Name < list[j].Name
		})
		conns := make([]api.CatalogConnection, len(list))
		for i, f := range list {
			conns[i] = f.CatalogConnection
		}
		out[item] = conns
	}
	return out, nil
}

// specRegistryItem is the catalog item the instance's spec was made from; empty for none.
func (s *Service) specRegistryItem(ctx context.Context, c authn.Caller, inst domain.Instance) (string, error) {
	if s.d.Specs == nil {
		return "", errors.New("connections: catalog's MCP server specs are not wired")
	}
	spec, ok, err := s.d.Specs.Get(ctx, c.Workspace, inst.ServerSpecID, catalogapi.MCPSpecGet{PlatformBacked: inst.PlatformManaged()})
	if err != nil || !ok || spec.RegistryItemID == nil {
		return "", err
	}
	return *spec.RegistryItemID, nil
}

// connectAction is the action naming url, with the caller's other
// connections from itemID when it is set (with_existing_connections).
func (s *Service) connectAction(ctx context.Context, c authn.Caller, name, url, itemID, exclude string) (*api.ConnectAction, error) {
	action := &api.ConnectAction{URL: url, Message: "Open this link to connect " + name + ": " + url}
	if itemID == "" {
		return action, nil
	}
	existing, err := s.OtherCatalogConnections(ctx, c, itemID, exclude)
	if err != nil || len(existing) == 0 {
		return action, err
	}
	names := make([]string, len(existing))
	for i, e := range existing {
		names[i] = e.Name
	}
	action.ExistingConnections = existing
	action.Message += " This workspace already has a connection from the same catalog item: " + strings.Join(names, ", ") + "."
	return action, nil
}

// InstanceConnectAction is _connect_action: the link a person opens to
// connect inst while it waits on a credential; nil when it does not.
func (s *Service) InstanceConnectAction(ctx context.Context, c authn.Caller, inst domain.Instance, probe bool, slug func() (string, error)) (*api.ConnectAction, error) {
	needs, err := s.NeedsConnecting(ctx, c, inst, probe)
	if err != nil || !needs {
		return nil, err
	}
	sl, err := slug()
	if err != nil {
		return nil, err
	}
	url, err := s.ConnectPageURL(sl, inst.ID)
	if err != nil {
		return nil, err
	}
	item, err := s.specRegistryItem(ctx, c, inst)
	if err != nil {
		return nil, err
	}
	return s.connectAction(ctx, c, inst.Name, url, item, inst.ID)
}

// ConnectionConnectAction is _openapi_connect_action: the link a person
// opens to sign in to a catalog connection again; nil when it needs none.
// A platform-managed connection is signed in by the operator.
func (s *Service) ConnectionConnectAction(ctx context.Context, c authn.Caller, conn domain.Connection, slug func() (string, error)) (*api.ConnectAction, error) {
	if conn.RegistryItemID == nil || conn.PlatformManaged() {
		return nil, nil
	}
	if conn.AuthConfigID != nil {
		authID, err := uuid.Parse(*conn.AuthConfigID)
		if err != nil {
			return nil, err
		}
		_, err = s.AuthHeaders(ctx, c.Workspace, authID, conn.BaseURL, false)
		var reauth *domain.ReauthRequired
		var invalid *domain.Invalid
		switch {
		case err == nil:
			return nil, nil
		case errors.As(err, &reauth), errors.As(err, &invalid):
			s.d.Log.InfoContext(ctx, "OpenAPI connection needs signing in again", "connection_id", conn.ID, "error", err)
		default:
			return nil, err
		}
	}
	sl, err := slug()
	if err != nil {
		return nil, err
	}
	url, err := s.ConnectPageURL(sl, "catalog/"+*conn.RegistryItemID)
	if err != nil {
		return nil, err
	}
	return s.connectAction(ctx, c, conn.Name, url, *conn.RegistryItemID, conn.ID)
}

// AllInstances are the instances the workspace sees (service.list).
func (s *Service) AllInstances(ctx context.Context, c authn.Caller) ([]domain.Instance, error) {
	rows, _, err := s.listInstances(ctx, c)
	return rows, err
}

// AllConnections are the OpenAPI connections the workspace sees.
func (s *Service) AllConnections(ctx context.Context, c authn.Caller) ([]domain.Connection, error) {
	return s.allConnections(ctx, c, ConnectionFilter{})
}

// FullConnection is the connection with its stored spec; false when the workspace has none.
func (s *Service) FullConnection(ctx context.Context, c authn.Caller, id uuid.UUID) (domain.Connection, bool, error) {
	return s.fullConnection(ctx, c.Workspace, id)
}

// CallInstanceTool is call_instance_tool: one of inst's tools run as c, the
// way a client's endpoint runs it. The caller's policy judges the call and
// the verdict is audited against the instance before anything runs; a call
// held for approval goes through its approval.
func (s *Service) CallInstanceTool(ctx context.Context, c authn.Caller, inst domain.Instance, raw string, args json.RawMessage) (map[string]any, error) {
	policy, err := s.callerPolicy(ctx, c)
	if err != nil {
		return nil, err
	}
	name := toolname.AggregateNamespace(nil, inst.ID, inst.Name) + toolname.NSSep + raw
	d := governanceapi.DecideToolPolicy(&policy, name, governanceapi.ToolNames{
		Aliases:     []string{toolname.MCPToolTarget(inst.ID, raw)},
		Restricting: toolname.MCPNarrowingNames(inst.Name, raw),
	})
	audit := toolAudit{resourceType: "mcp_instance", resourceID: inst.ID, actorType: actorOf(c), name: name, args: args,
		extra: map[string]any{"mcp_instance_id": inst.ID}}
	held := func() runsapi.HeldCall {
		names := governanceapi.ToolNames{Aliases: []string{toolname.MCPToolTarget(inst.ID, raw)}, Restricting: toolname.MCPNarrowingNames(inst.Name, raw)}
		return heldCall(c, &policy, name, names, inst.ID, inst.Name, raw, "", args, d.Reason)
	}
	out, refused, err := s.judged(ctx, c, c.ClientID, audit, d, held, mcpBinding(inst.ID, raw), func() (any, error) {
		return s.runInstanceTool(ctx, c, inst, raw, args)
	})
	if err != nil {
		return nil, err
	}
	if refused != "" {
		return map[string]any{"content": []map[string]any{{"type": "text", "text": refused}}, "isError": true}, nil
	}
	return out.(map[string]any), nil
}

func (s *Service) runInstanceTool(ctx context.Context, c authn.Caller, inst domain.Instance, raw string, args json.RawMessage) (map[string]any, error) {
	up, err := s.UpstreamFor(ctx, c.Workspace, inst, &CallerContext{UserID: c.UserID, UserEmail: c.Email, ClientID: c.ClientID, Tool: raw})
	var invalid *domain.Invalid
	if errors.As(err, &invalid) && invalid.Msg == errNoUpstreamURL {
		return map[string]any{"content": []map[string]any{{"type": "text", "text": inst.Name + " is unreachable: no address"}}, "isError": true}, nil
	}
	if err != nil {
		return nil, err
	}
	arguments := map[string]any{}
	if len(args) > 0 && string(args) != "null" {
		if err := decodeUseNumber(args, &arguments); err != nil {
			return nil, err
		}
	}
	res, err := withClient(ctx, up, func(cl *mcpclient.Client) (*mcpclient.CallResult, error) {
		return cl.CallTool(ctx, mcpclient.Call{Name: raw, Arguments: arguments})
	})
	if err != nil {
		return nil, err
	}
	return callResultJSON(res), nil
}

// CallOpenAPITool is call_openapi_tool: the operation run as c, judged by
// c's policy and audited against the connection.
func (s *Service) CallOpenAPITool(ctx context.Context, c authn.Caller, connectionID, operation string, args json.RawMessage) (ToolResult, error) {
	return s.callConnectionTool(ctx, c, connectionID, operation, args, true)
}

// ReadableIDs are the resources the graph says c may read (readable_resource_ids).
func (s *Service) ReadableIDs(ctx context.Context, c authn.Caller) (map[string]struct{}, error) {
	lister, ok := s.d.Graph.(authz.Lister)
	if !ok {
		return nil, errors.New("connections: the authorization graph cannot list readable resources")
	}
	return authz.ReadableResourceIDs(ctx, lister, c.GraphSubject())
}

// OperationHints is _openapi_hints: each operation's safety hint from its
// HTTP method, none for a connection whose spec does not parse.
func (s *Service) OperationHints(ctx context.Context, conn domain.Connection) map[string]string {
	out := map[string]string{}
	if conn.SpecContent == nil {
		return out
	}
	ops, err := openapispec.ParseOperations(conn.SpecContent, nil)
	if err != nil {
		s.d.Log.WarnContext(ctx, "OpenAPI connection has an unreadable spec", "connection_id", conn.ID, "error", err)
		return out
	}
	for _, op := range ops {
		switch strings.ToUpper(op.Method) {
		case "DELETE":
			out[op.Name] = "destructive"
		case "GET", "HEAD":
			out[op.Name] = "read-only"
		default:
			out[op.Name] = ""
		}
	}
	return out
}

// MCPSpec is get_server_by_id: the workspace's spec, a catalog mirror or a
// catalog projection; false when there is none.
func (s *Service) MCPSpec(ctx context.Context, c authn.Caller, id string) (catalogapi.MCPSpec, bool, error) {
	if s.d.Specs == nil {
		return catalogapi.MCPSpec{}, false, errors.New("connections: catalog's MCP server specs are not wired")
	}
	return s.d.Specs.Get(ctx, c.Workspace, id, catalogapi.MCPSpecGet{})
}
