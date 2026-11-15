package service

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
	govapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// Clients serves the client routes (registered harnesses, runner keys).
type Clients struct {
	s *Service
	p ClientPorts
}

// NewClients builds the service over the agents service.
func NewClients(s *Service, p ClientPorts) *Clients { return &Clients{s: s, p: p} }

// ErrClientNotFound is the routes' HTTPException(404, "Client not found").
var ErrClientNotFound = errors.New("client not found")

// ErrClientRunnerKeyNotFound is HTTPException(404, "Runner key not found").
var ErrClientRunnerKeyNotFound = errors.New("runner key not found")

// ErrClientNoRunner is HTTPException(422, "Only a Codex or Claude Code client has a runner").
var ErrClientNoRunner = errors.New("Only a Codex or Claude Code client has a runner") //nolint:staticcheck // Python's detail

// ClientInUseError is delete's ConflictError: agents still run on the client.
type ClientInUseError struct{ Agents int64 }

func (e *ClientInUseError) Error() string {
	return fmt.Sprintf("%d agent(s) run on this client; move them to a model or another client before deleting it", e.Agents)
}

// ClientRef is a skill attached to a client.
type ClientRef struct {
	ID   string
	Name string
}

// ClientLinkRef is an attached MCP instance or OpenAPI connection; AllowedTools is the stored JSON.
type ClientLinkRef struct {
	ID              string
	Name            string
	NamespacePrefix *string
	AllowedTools    []byte
}

// ClientView is ClientResponse.
type ClientView struct {
	store.ClientRow
	Skills             []ClientRef
	MCPInstances       []ClientLinkRef
	OpenAPIConnections []ClientLinkRef
	Toolsets           []store.ClientToolsetLink
	EndpointURL        string
	Online             bool
	HasRunner          bool
}

// ClientPatch is ClientUpdate after validation; nil and unset fields stay.
type ClientPatch struct {
	Name         *string
	Description  Set[string]
	Kind         *string
	DefaultModel Set[string]
	AllowDomains *[]string
	Sandbox      *bool
}

func clientStore() store.Clients { return store.Clients{} }

// ClientEndpointURL is client_mcp_endpoint_url.
func (x *Clients) ClientEndpointURL(id string) string {
	return strings.TrimRight(x.p.APIURL, " /") + "/mcp/clients/" + id
}

func (x *Clients) views(ctx context.Context, ws scope.Workspace, rows []store.ClientRow) ([]ClientView, error) {
	ids := make([]uuid.UUID, len(rows))
	for i, r := range rows {
		ids[i] = r.ID
	}
	var (
		skills   []store.ClientSkillLink
		mcp      []store.ClientLink
		openapi  []store.ClientLink
		toolsets []store.ClientToolsetLink
	)
	if len(ids) > 0 {
		if err := x.s.read(ctx, ws, func(sess db.Session) error {
			var err error
			if skills, err = clientStore().Skills(ctx, sess, ids); err != nil {
				return err
			}
			if mcp, err = clientStore().MCPInstances(ctx, sess, ids); err != nil {
				return err
			}
			if openapi, err = clientStore().OpenAPIConnections(ctx, sess, ids); err != nil {
				return err
			}
			toolsets, err = clientStore().Toolsets(ctx, sess, ids)
			return err
		}); err != nil {
			return nil, err
		}
	}
	mcpNames, err := x.linkNames(ctx, ws, mcp, func() (func(context.Context, scope.Workspace, []string) (map[string]string, error), bool) {
		if x.p.MCPNames == nil {
			return nil, false
		}
		return x.p.MCPNames.MCPInstanceNames, true
	}, "naming a client's MCP instances")
	if err != nil {
		return nil, err
	}
	openapiNames, err := x.linkNames(ctx, ws, openapi, func() (func(context.Context, scope.Workspace, []string) (map[string]string, error), bool) {
		if x.p.Connections == nil {
			return nil, false
		}
		return x.p.Connections.OpenAPIConnectionNames, true
	}, "naming a client's OpenAPI connections")
	if err != nil {
		return nil, err
	}
	online := map[string]bool{}
	if x.s.d.Presence != nil {
		var runners []string
		for _, r := range rows {
			if domain.RunnerKind(r.Kind) {
				runners = append(runners, r.ID.String())
			}
		}
		if len(runners) > 0 {
			if online, err = x.s.d.Presence.Online(ctx, runners); err != nil {
				return nil, err
			}
		}
	}
	out := make([]ClientView, len(rows))
	for i, r := range rows {
		v := ClientView{ClientRow: r, EndpointURL: x.ClientEndpointURL(r.ID.String()),
			Online: domain.RunnerKind(r.Kind) && online[r.ID.String()], HasRunner: domain.RunnerKind(r.Kind),
			Skills: []ClientRef{}, MCPInstances: []ClientLinkRef{}, OpenAPIConnections: []ClientLinkRef{}, Toolsets: []store.ClientToolsetLink{}}
		for _, s := range skills {
			if s.ClientID == r.ID {
				v.Skills = append(v.Skills, ClientRef{ID: s.SkillID.String(), Name: s.Name})
			}
		}
		v.MCPInstances = clientRefs(r.ID, mcp, mcpNames)
		v.OpenAPIConnections = clientRefs(r.ID, openapi, openapiNames)
		sort.SliceStable(v.OpenAPIConnections, func(a, b int) bool { return v.OpenAPIConnections[a].Name < v.OpenAPIConnections[b].Name })
		for _, t := range toolsets {
			if t.ClientID == r.ID {
				v.Toolsets = append(v.Toolsets, t)
			}
		}
		out[i] = v
	}
	return out, nil
}

func (x *Clients) linkNames(ctx context.Context, ws scope.Workspace, links []store.ClientLink,
	port func() (func(context.Context, scope.Workspace, []string) (map[string]string, error), bool), feature string,
) (map[string]string, error) {
	if len(links) == 0 {
		return map[string]string{}, nil
	}
	names, ok := port()
	if !ok {
		return nil, &UnwiredError{Feature: feature}
	}
	seen := map[string]bool{}
	var ids []string
	for _, l := range links {
		if id := l.TargetID.String(); !seen[id] {
			seen[id] = true
			ids = append(ids, id)
		}
	}
	return names(ctx, ws, ids)
}

func clientRefs(client uuid.UUID, links []store.ClientLink, names map[string]string) []ClientLinkRef {
	out := []ClientLinkRef{}
	for _, l := range links {
		if l.ClientID != client {
			continue
		}
		if name, ok := names[l.TargetID.String()]; ok {
			out = append(out, ClientLinkRef{ID: l.TargetID.String(), Name: name, NamespacePrefix: l.NamespacePrefix, AllowedTools: l.AllowedTools})
		}
	}
	return out
}

func (x *Clients) one(ctx context.Context, ws scope.Workspace, id uuid.UUID) (ClientView, error) {
	var row store.ClientRow
	var found bool
	if err := x.s.read(ctx, ws, func(sess db.Session) error {
		var err error
		row, found, err = clientStore().Get(ctx, sess, id)
		return err
	}); err != nil {
		return ClientView{}, err
	}
	if !found {
		return ClientView{}, ErrClientNotFound
	}
	vs, err := x.views(ctx, ws, []store.ClientRow{row})
	if err != nil {
		return ClientView{}, err
	}
	return vs[0], nil
}

// List is list_clients: the clients the caller may read.
func (x *Clients) List(ctx context.Context, c authn.Caller, limit, offset int32) ([]ClientView, error) {
	readable, err := authz.ReadableResourceIDs(ctx, x.s.d.Graph, c.GraphSubject())
	if err != nil {
		return nil, err
	}
	ids := make([]uuid.UUID, 0, len(readable))
	for id := range readable {
		if u, err := uuid.Parse(id); err == nil {
			ids = append(ids, u)
		}
	}
	var rows []store.ClientRow
	if err := x.s.read(ctx, c.Workspace, func(sess db.Session) error {
		rows, err = clientStore().List(ctx, sess, ids, offset, limit)
		return err
	}); err != nil {
		return nil, err
	}
	return x.views(ctx, c.Workspace, rows)
}

// Create is create_client plus the owner grant, before the commit.
func (x *Clients) Create(ctx context.Context, c authn.Caller, name string, description *string, kind string) (ClientView, error) {
	id := uuid.New()
	if err := x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := clientStore().Insert(ctx, sess, id, c.UserID, name, description, kind, x.s.d.Now()); err != nil {
			return err
		}
		return authz.GrantResourceOwner(ctx, x.s.d.Graph, id.String(), c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations())
	}); err != nil {
		return ClientView{}, err
	}
	return x.one(ctx, c.Workspace, id)
}

// Get is get_client.
func (x *Clients) Get(ctx context.Context, c authn.Caller, id uuid.UUID) (ClientView, error) {
	return x.one(ctx, c.Workspace, id)
}

// Update is update_client: the fields the patch sets.
func (x *Clients) Update(ctx context.Context, c authn.Caller, id uuid.UUID, p ClientPatch) (ClientView, error) {
	var found bool
	if err := x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		row, ok, err := clientStore().Get(ctx, sess, id)
		found = ok
		if err != nil || !ok {
			return err
		}
		if p.Name != nil {
			row.Name = *p.Name
		}
		if p.Description.Set {
			row.Description = p.Description.Value
		}
		if p.Kind != nil {
			row.Kind = *p.Kind
		}
		if p.DefaultModel.Set {
			row.DefaultModel = p.DefaultModel.Value
		}
		if p.AllowDomains != nil {
			domains := make([]any, len(*p.AllowDomains))
			for i, d := range *p.AllowDomains {
				domains[i] = d
			}
			if row.AllowDomains, err = wirejson.Marshal(domains, wirejson.Dumps); err != nil {
				return err
			}
		}
		if p.Sandbox != nil {
			row.Sandbox = *p.Sandbox
		}
		return clientStore().Update(ctx, sess, row, x.s.d.Now())
	}); err != nil {
		return ClientView{}, err
	}
	if !found {
		return ClientView{}, ErrClientNotFound
	}
	return x.one(ctx, c.Workspace, id)
}

// Delete is delete_client: refused while agents run on it; the graph tuples go after the commit.
func (x *Clients) Delete(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	var deleted bool
	if err := x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		_, ok, err := clientStore().Get(ctx, sess, id)
		if err != nil || !ok {
			return err
		}
		n, err := clientStore().AgentCount(ctx, sess, id)
		if err != nil {
			return err
		}
		if n > 0 {
			return &ClientInUseError{Agents: n}
		}
		deleted, err = clientStore().Delete(ctx, sess, id)
		return err
	}); err != nil {
		return err
	}
	if !deleted {
		return ErrClientNotFound
	}
	if rw, ok := x.s.d.Graph.(authz.ReadWriter); ok {
		if err := authz.RevokeResource(ctx, rw, id.String()); err != nil && x.s.d.Log != nil {
			x.s.d.Log.WarnContext(ctx, "Deleted Client but could not remove its graph tuples", "client_id", id.String(), "error", err.Error())
		}
	}
	return nil
}

func clientNotFound(label string) error { return &domain.NotFoundError{Message: label + " not found"} }

// inWorkspace is ClientService._in_workspace for the client: NotFoundError("Client not found").
func (x *Clients) inWorkspace(ctx context.Context, sess db.Session, id uuid.UUID) error {
	_, ok, err := clientStore().Get(ctx, sess, id)
	if err == nil && !ok {
		err = clientNotFound("Client")
	}
	return err
}

// AddSkill is add_skill: both ends in the workspace.
func (x *Clients) AddSkill(ctx context.Context, c authn.Caller, client uuid.UUID, skill string) error {
	return x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := x.inWorkspace(ctx, sess, client); err != nil {
			return err
		}
		sk, err := uuid.Parse(skill)
		if err != nil || !domain.TaskDefPythonUUID(skill) {
			return clientNotFound("Skill")
		}
		ok, err := (store.Lookup{}).SkillExists(ctx, sess, sk)
		if err != nil {
			return err
		}
		if !ok {
			return clientNotFound("Skill")
		}
		return clientStore().AddSkill(ctx, sess, client, sk)
	})
}

// RemoveSkill is remove_skill; detaching what is not attached changes nothing.
func (x *Clients) RemoveSkill(ctx context.Context, c authn.Caller, client, skill uuid.UUID) error {
	return x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := x.inWorkspace(ctx, sess, client); err != nil {
			return err
		}
		return clientStore().RemoveSkill(ctx, sess, client, skill)
	})
}

// usableConnection is ClientService._usable_connection.
func (x *Clients) usableConnection(ctx context.Context, c authn.Caller, raw, label string,
	look func(ctx context.Context, ws scope.Workspace, id string) (bool, bool, error),
) (uuid.UUID, error) {
	id, err := uuid.Parse(raw)
	if err != nil || !domain.TaskDefPythonUUID(raw) {
		return uuid.Nil, clientNotFound(label)
	}
	found, platform, err := look(ctx, c.Workspace, id.String())
	if err != nil {
		return uuid.Nil, err
	}
	if !found {
		return uuid.Nil, clientNotFound(label)
	}
	if !platform {
		allowed, err := x.s.d.Graph.Check(ctx, c.GraphSubject(), authz.CanUseConnection, authz.TypeResource, id.String())
		if err != nil {
			return uuid.Nil, err
		}
		if !allowed {
			return uuid.Nil, &PermissionError{Msg: "This " + label + " is someone else's personal connection; its owner can share it with the workspace."}
		}
	}
	return id, nil
}

func (x *Clients) checkClient(ctx context.Context, ws scope.Workspace, client uuid.UUID) error {
	return x.s.read(ctx, ws, func(sess db.Session) error { return x.inWorkspace(ctx, sess, client) })
}

func clientAllowedJSON(tools *[]string) ([]byte, error) {
	if tools == nil {
		return nil, nil
	}
	list := make([]any, len(*tools))
	for i, t := range *tools {
		list[i] = t
	}
	return wirejson.Marshal(list, wirejson.Dumps)
}

// AddMCPInstance is add_mcp_instance: attach, or replace how an attached instance is served.
func (x *Clients) AddMCPInstance(ctx context.Context, c authn.Caller, client uuid.UUID, instance string, prefix *string, allowed *[]string) error {
	if err := x.checkClient(ctx, c.Workspace, client); err != nil {
		return err
	}
	if x.p.Connections == nil {
		return &UnwiredError{Feature: "attaching an MCP instance to a client"}
	}
	id, err := x.usableConnection(ctx, c, instance, "MCP instance", x.p.Connections.MCPInstance)
	if err != nil {
		return err
	}
	raw, err := clientAllowedJSON(allowed)
	if err != nil {
		return err
	}
	return x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		return clientStore().SetMCPInstance(ctx, sess, client, id, prefix, raw)
	})
}

// RemoveMCPInstance is remove_mcp_instance.
func (x *Clients) RemoveMCPInstance(ctx context.Context, c authn.Caller, client, instance uuid.UUID) error {
	return x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := x.inWorkspace(ctx, sess, client); err != nil {
			return err
		}
		return clientStore().RemoveMCPInstance(ctx, sess, client, instance)
	})
}

// AddOpenAPIConnection is add_openapi_connection.
func (x *Clients) AddOpenAPIConnection(ctx context.Context, c authn.Caller, client uuid.UUID, conn string, prefix *string, allowed *[]string) error {
	if err := x.checkClient(ctx, c.Workspace, client); err != nil {
		return err
	}
	if x.p.Connections == nil {
		return &UnwiredError{Feature: "attaching an OpenAPI connection to a client"}
	}
	id, err := x.usableConnection(ctx, c, conn, "OpenAPI connection", x.p.Connections.OpenAPIConnection)
	if err != nil {
		return err
	}
	raw, err := clientAllowedJSON(allowed)
	if err != nil {
		return err
	}
	return x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		return clientStore().SetOpenAPIConnection(ctx, sess, client, id, prefix, raw)
	})
}

// RemoveOpenAPIConnection is remove_openapi_connection.
func (x *Clients) RemoveOpenAPIConnection(ctx context.Context, c authn.Caller, client, conn uuid.UUID) error {
	return x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := x.inWorkspace(ctx, sess, client); err != nil {
			return err
		}
		return clientStore().RemoveOpenAPIConnection(ctx, sess, client, conn)
	})
}

// SetToolset is add_platform_toolset_to_client: ref resolves to a namespace
// first (a *domain.ClientToolsetError when it cannot), then the client.
func (x *Clients) SetToolset(ctx context.Context, c authn.Caller, client uuid.UUID, ref string, disabled *[]string) (string, error) {
	var methods []string
	if disabled != nil {
		methods = *disabled
	}
	ns, err := domain.ClientAttachableToolset(ref, methods)
	if err != nil {
		return "", err
	}
	raw, err := clientAllowedJSON(disabled)
	if err != nil {
		return "", err
	}
	return ns, x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := x.inWorkspace(ctx, sess, client); err != nil {
			return err
		}
		return clientStore().SetToolset(ctx, sess, client, ns, raw)
	})
}

// RemoveToolset is remove_platform_toolset, by the namespace the client lists.
func (x *Clients) RemoveToolset(ctx context.Context, c authn.Caller, client uuid.UUID, toolset string) error {
	return x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := x.inWorkspace(ctx, sess, client); err != nil {
			return err
		}
		return clientStore().RemoveToolset(ctx, sess, client, toolset)
	})
}

// HarnessAgent is AgentService.harness_agent: the agent a task given to the
// client itself runs as, made on first use.
func (x *Clients) HarnessAgent(ctx context.Context, c authn.Caller, id uuid.UUID) (View, error) {
	s := x.s
	bad := &domain.InvalidError{Code: domain.CodeInvalidClientID, Detail: fmt.Sprintf(
		"Client '%s' is no Codex or Claude Code client of this workspace", id)}
	var row store.ClientRow
	var found bool
	if err := s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		row, found, err = clientStore().Get(ctx, sess, id)
		return err
	}); err != nil {
		return View{}, err
	}
	if !found || !domain.RunnerKind(row.Kind) {
		return View{}, bad
	}
	if err := s.Require(ctx, c, "use", id); err != nil {
		if errors.Is(err, ErrDenied) {
			return View{}, bad
		}
		return View{}, err
	}
	var a domain.Agent
	if err := retrySlug(func() error {
		return s.write(ctx, c.Workspace, func(sess db.Session) error {
			if err := db.XactLock(ctx, sess.Q(), db.TextKey("harness-agent:"+id.String())); err != nil {
				return err
			}
			existing, err := s.store.ByHarnessClient(ctx, sess, id)
			if err != nil || len(existing) > 0 {
				if err == nil {
					a = existing[0]
				}
				return err
			}
			client := id.String()
			a = domain.Agent{
				ID: uuid.NewString(), Name: row.Name, Status: domain.StatusActive, ClientID: &client, HarnessClientID: &client,
				Tools: []byte("[]"), A2UIEnabled: ptr(false), AgentType: "stateless",
			}
			return s.insertAgent(ctx, sess, c, &a, nil, s.d.Now())
		})
	}); err != nil {
		return View{}, err
	}
	vs, err := s.views(ctx, c.Workspace, []domain.Agent{a})
	if err != nil {
		return View{}, err
	}
	return vs[0], nil
}

// runnerClient is _runner_client: the workspace's client, else ErrClientNotFound.
func (x *Clients) runnerClient(ctx context.Context, ws scope.Workspace, id uuid.UUID) (store.ClientRow, error) {
	var row store.ClientRow
	var found bool
	if err := x.s.read(ctx, ws, func(sess db.Session) error {
		var err error
		row, found, err = clientStore().Get(ctx, sess, id)
		return err
	}); err != nil {
		return store.ClientRow{}, err
	}
	if !found {
		return store.ClientRow{}, ErrClientNotFound
	}
	return row, nil
}

// IssueRunnerKey is issue_runner_key after the scope and edit checks.
func (x *Clients) IssueRunnerKey(ctx context.Context, c authn.Caller, id uuid.UUID) (ClientRunnerKey, string, error) {
	row, err := x.runnerClient(ctx, c.Workspace, id)
	if err != nil {
		return ClientRunnerKey{}, "", err
	}
	if !domain.RunnerKind(row.Kind) {
		return ClientRunnerKey{}, "", ErrClientNoRunner
	}
	if x.p.RunnerKeys == nil {
		return ClientRunnerKey{}, "", &UnwiredError{Feature: "issuing runner keys"}
	}
	key, secret, err := x.p.RunnerKeys.Issue(ctx, c, id.String(), "runner: "+row.Name)
	if err != nil {
		return ClientRunnerKey{}, "", err
	}
	x.auditKey(ctx, c, "api_key.create", key.ID, map[string]any{
		"resource_name": key.Name, "token_prefix": key.Prefix, "client_id": id.String()})
	return key, secret, nil
}

// ListRunnerKeys is list_runner_keys: the client's live keys.
func (x *Clients) ListRunnerKeys(ctx context.Context, c authn.Caller, id uuid.UUID) ([]ClientRunnerKey, error) {
	if _, err := x.runnerClient(ctx, c.Workspace, id); err != nil {
		return nil, err
	}
	if x.p.RunnerKeys == nil {
		return nil, &UnwiredError{Feature: "listing runner keys"}
	}
	keys, err := x.p.RunnerKeys.List(ctx, c, id.String())
	if err != nil {
		return nil, err
	}
	out := []ClientRunnerKey{}
	for _, k := range keys {
		if k.Active {
			out = append(out, k)
		}
	}
	return out, nil
}

// RevokeRunnerKey is revoke_runner_key after the scope and edit checks.
func (x *Clients) RevokeRunnerKey(ctx context.Context, c authn.Caller, id, keyID uuid.UUID) error {
	if _, err := x.runnerClient(ctx, c.Workspace, id); err != nil {
		return err
	}
	if x.p.RunnerKeys == nil {
		return &UnwiredError{Feature: "revoking runner keys"}
	}
	key, found, err := x.p.RunnerKeys.Get(ctx, c, keyID.String())
	if err != nil {
		return err
	}
	if !found || key.ClientID == nil || *key.ClientID != id.String() || !key.Active {
		return ErrClientRunnerKeyNotFound
	}
	if err := x.p.RunnerKeys.Revoke(ctx, c, keyID.String()); err != nil {
		return err
	}
	x.auditKey(ctx, c, "api_key.revoke", keyID.String(), map[string]any{"client_id": id.String(), "token_prefix": key.Prefix})
	return nil
}

// auditKey is audit.record with event_metadata, in its own transaction; a failure is logged.
func (x *Clients) auditKey(ctx context.Context, c authn.Caller, action, keyID string, meta map[string]any) {
	s := x.s
	if s.d.Audit == nil {
		return
	}
	if cr := c.Credential; cr != nil {
		meta["credential"] = string(cr.Kind)
		meta["surface"] = string(cr.Surface)
		if cr.KeyID != "" {
			k := "api_key_id"
			if cr.Kind == authn.KindTurn {
				k = "turn_id"
			}
			meta[k] = cr.KeyID
		}
	}
	err := s.write(ctx, c.Workspace, func(sess db.Session) error {
		return s.d.Audit.RecordOnce(ctx, sess, govapi.AuditRecord{
			EventID: uuid.NewString(), Action: action, ResourceType: "api_key", ResourceID: keyID,
			ActorType: "user", ActorID: c.UserID, Metadata: meta,
		})
	})
	if err != nil && s.d.Log != nil {
		s.d.Log.WarnContext(ctx, "Failed to record audit event", "action", action, "resource_type", "api_key", "error", err.Error())
	}
}
