// Package authn is the cluster adapter of kernel/authn: every way a caller
// is authenticated today, with Python's resolution order, refusals and
// resulting principal (auth/dependencies.py).
//
// Token order (_verify_token): a turn token (header kid agentarea-turn),
// then an API key (aat_), then a Kratos session JWT (ES256, static JWKS),
// then a Hydra OAuth JWT (RS256, Hydra's JWKS) when Kratos refuses or cannot
// be built. Only the Authorization bearer header is read.
package authn

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"sync"
	"time"

	port "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// APIKey is the api_keys row authentication reads. AgentID and ClientID are
// empty when null; ExpiresAt and LastAccessedAt are naive UTC.
type APIKey struct {
	ID             string
	WorkspaceID    string
	CreatedBy      string
	IsActive       bool
	ExpiresAt      *time.Time
	LastAccessedAt *time.Time
	AgentID        string
	ClientID       string
}

// Workspace is the workspaces row authentication reads.
type Workspace struct {
	ID          string
	Slug        string
	OwnerUserID string
}

// Store is the database access authentication needs; the cluster
// implementation is authn/store over the primary (write) pool, since a key
// revoked a moment ago must not pass on a lagging replica.
type Store interface {
	// APIKeyByHash finds a key of any workspace by its token_hash.
	APIKeyByHash(ctx context.Context, tokenHash string) (APIKey, bool, error)
	// RecordAPIKeyUse adds uses to access_count and stamps last_accessed_at.
	RecordAPIKeyUse(ctx context.Context, keyID string, uses int, at time.Time) error
	WorkspaceByID(ctx context.Context, id string) (Workspace, bool, error)
	WorkspaceBySlug(ctx context.Context, slug string) (Workspace, bool, error)
	// OwnedOrNamed is the workspaces userID owns plus the one slug or id
	// names (either may be empty), oldest first.
	OwnedOrNamed(ctx context.Context, userID, slug, id string) ([]Workspace, error)
}

// Graph is the membership graph: Workspace#members.
type Graph interface {
	authz.Checker
	authz.Reader
}

// Reach is the authorization extension's extra reach
// (AuthorizationService.get_accessible_workspaces); nil grants nothing.
type Reach interface {
	AccessibleWorkspaces(ctx context.Context, p port.Principal) ([]string, error)
}

// Deps are the adapters the gate uses.
type Deps struct {
	Store Store
	Graph Graph
	// LiveTurns is required when the gateway secret is set.
	LiveTurns port.LiveTurns
	Reach     Reach
	// HTTP fetches Hydra's JWKS; nil uses a client that follows no redirects.
	HTTP *http.Client
	Now  func() time.Time
	Log  *slog.Logger
}

// apiKeyUseWriteInterval bounds use-count writes per key (API_KEY_USE_WRITE_INTERVAL).
const apiKeyUseWriteInterval = 60 * time.Second

// Gate implements kernel authn.Gate.
type Gate struct {
	store     Store
	graph     Graph
	live      port.LiveTurns
	reach     Reach
	kratos    *kratos
	hydra     *hydra
	turnKey   []byte
	challenge string
	now       func() time.Time
	log       *slog.Logger

	usesMu sync.Mutex
	// uses counted but not written yet, by key id; they ride with the key's next write.
	uses map[string]int
}

var _ port.Gate = (*Gate)(nil)

// New builds the gate.
func New(cfg Config, d Deps) (*Gate, error) {
	if d.Store == nil || d.Graph == nil {
		return nil, errors.New("authn: Store and Graph are required")
	}
	if err := checkHydraURL(cfg.HydraURL); err != nil {
		return nil, fmt.Errorf("authn: AGENTAREA_AUTH_HYDRA_URL %w", err)
	}
	if cfg.GatewaySecret != "" && d.LiveTurns == nil {
		return nil, errors.New("authn: live runner turns are kept in Redis; LiveTurns is required when AGENTAREA_MCP_GATEWAY_SECRET is set")
	}
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	if d.HTTP == nil {
		d.HTTP = newJWKSClient()
	}
	g := &Gate{
		store:     d.Store,
		graph:     d.Graph,
		live:      d.LiveTurns,
		reach:     d.Reach,
		kratos:    newKratos(cfg),
		hydra:     newHydra(cfg, d.HTTP, d.Log),
		challenge: port.Challenge(cfg.APIURL),
		now:       d.Now,
		log:       d.Log,
		uses:      map[string]int{},
	}
	if cfg.GatewaySecret != "" {
		tokens, err := NewTurnTokens(cfg.GatewaySecret, d.Now)
		if err != nil {
			return nil, err
		}
		g.turnKey = tokens.key
	}
	return g, nil
}

func (g *Gate) unauthorized(detail string) *port.Error {
	return &port.Error{Status: http.StatusUnauthorized, Detail: detail, WWWAuthenticate: g.challenge}
}

func forbidden(detail string) *port.Error {
	return &port.Error{Status: http.StatusForbidden, Detail: detail}
}

// Authenticate is authenticate_principal. It verifies the token each call:
// the HTTP edge calls it once per request and keeps the principal in the
// context, so an API key use is counted once.
func (g *Gate) Authenticate(ctx context.Context, r *http.Request) (port.Principal, error) {
	token, ok := port.BearerToken(r)
	if !ok {
		return port.Principal{}, g.unauthorized(port.DetailMissingCredentials)
	}
	p, err := g.Verify(ctx, token)
	if err != nil {
		return port.Principal{}, err
	}
	if p.Credential != nil && !p.Credential.Reaches(port.SurfaceAPI) {
		return port.Principal{}, g.insufficientScope(port.OAuthScopeAPI)
	}
	return p, nil
}

// insufficientScope is RFC 6750's 403 for a valid token that lacks scope.
func (g *Gate) insufficientScope(scope string) *port.Error {
	challenge := g.challenge + `, error="insufficient_scope", scope="` + scope + `"`
	return &port.Error{Status: http.StatusForbidden, Detail: port.DetailInsufficientScope, WWWAuthenticate: challenge}
}

// Verify is _verify_token.
func (g *Gate) Verify(ctx context.Context, token string) (port.Principal, error) {
	if isTurnToken(token) {
		p, ok, err := g.verifyTurn(ctx, token)
		if err != nil {
			return port.Principal{}, err
		}
		if !ok {
			return port.Principal{}, g.unauthorized(port.DetailTurnEnded)
		}
		return p, nil
	}
	if strings.HasPrefix(token, port.APIKeyPrefix) {
		p, ok, err := g.verifyAPIKey(ctx, token)
		if err != nil {
			return port.Principal{}, err
		}
		if !ok {
			return port.Principal{}, g.unauthorized(port.DetailInvalidAPIKey)
		}
		return p, nil
	}

	now := g.now()
	result, kratosErr := g.kratos.verify(token, unixSeconds(now))
	if kratosErr != nil {
		p, err := g.hydra.try(ctx, token, now)
		if err != nil {
			return port.Principal{}, err
		}
		if p != nil {
			return *p, nil
		}
		g.log.Error("Unexpected error during authentication", "error", kratosErr.Error())
		return port.Principal{}, &port.Error{Status: http.StatusInternalServerError, Detail: port.DetailAuthInternal}
	}
	if result.authenticated() {
		return port.Principal{
			UserID:     result.userID,
			Email:      result.email,
			Credential: &port.Credential{Kind: port.KindSession, Surface: port.SurfaceAPI},
		}, nil
	}
	p, err := g.hydra.try(ctx, token, now)
	if err != nil {
		return port.Principal{}, err
	}
	if p != nil {
		return *p, nil
	}
	g.log.Warn("Authentication failed", "error", result.error)
	detail := result.error
	if detail == "" {
		detail = port.DetailInvalidToken
	}
	return port.Principal{}, g.unauthorized(detail)
}

func userSubject(userID string) string {
	if strings.HasPrefix(userID, "User:") {
		return userID
	}
	return "User:" + userID
}

// ownsWorkspace is is_workspace_owner: the personal workspace, or a row owned.
func (g *Gate) ownsWorkspace(ctx context.Context, userID, workspaceID string) (bool, error) {
	if workspaceID == userID {
		return true, nil
	}
	ws, found, err := g.store.WorkspaceByID(ctx, workspaceID)
	if err != nil {
		return false, err
	}
	return found && ws.OwnerUserID == userID, nil
}

// hasGraphMembership is _has_graph_membership: a graph failure denies.
func (g *Gate) hasGraphMembership(ctx context.Context, userID, workspaceID string) bool {
	ok, err := g.graph.Check(ctx, userSubject(userID), "members", "Workspace", workspaceID)
	if err != nil {
		g.log.Error("Could not check membership", "user_id", userID, "workspace_id", workspaceID, "error", err.Error())
		return false
	}
	return ok
}

// verifyAPIKey is _validate_api_key: a key is only as good as its creator's
// current membership of the key's workspace.
func (g *Gate) verifyAPIKey(ctx context.Context, token string) (port.Principal, bool, error) {
	key, found, err := g.store.APIKeyByHash(ctx, port.HashAPIKey(token))
	if err != nil {
		return port.Principal{}, false, err
	}
	if !found || !key.IsActive {
		return port.Principal{}, false, nil
	}
	if key.ExpiresAt != nil && !g.now().UTC().Before(*key.ExpiresAt) {
		return port.Principal{}, false, nil
	}
	owned, err := g.ownsWorkspace(ctx, key.CreatedBy, key.WorkspaceID)
	if err != nil {
		return port.Principal{}, false, err
	}
	if !owned && !g.hasGraphMembership(ctx, key.CreatedBy, key.WorkspaceID) {
		g.log.Warn("API key refused: its owner is not a member of its workspace",
			"key_id", key.ID, "user_id", key.CreatedBy, "workspace_id", key.WorkspaceID)
		return port.Principal{}, false, nil
	}
	if key.CreatedBy == "" {
		return port.Principal{}, false, port.ErrNoPrincipal
	}
	g.recordAPIKeyUse(ctx, key.ID, key.LastAccessedAt)
	return port.Principal{
		UserID:           key.CreatedBy,
		BoundWorkspaceID: key.WorkspaceID,
		BoundAgentID:     key.AgentID,
		BoundClientID:    key.ClientID,
		Credential:       &port.Credential{Kind: port.KindAPIKey, KeyID: key.ID, Surface: port.SurfaceAPI},
	}, true, nil
}

// recordAPIKeyUse is _record_api_key_use: count one use, write at most once
// per interval; a failed write keeps its uses for the next one.
func (g *Gate) recordAPIKeyUse(ctx context.Context, keyID string, lastWritten *time.Time) {
	now := g.now().UTC()
	g.usesMu.Lock()
	g.uses[keyID]++
	if lastWritten != nil && now.Sub(*lastWritten) < apiKeyUseWriteInterval {
		g.usesMu.Unlock()
		return
	}
	uses := g.uses[keyID]
	delete(g.uses, keyID)
	g.usesMu.Unlock()
	if err := g.store.RecordAPIKeyUse(ctx, keyID, uses, now); err != nil {
		g.usesMu.Lock()
		g.uses[keyID] += uses
		g.usesMu.Unlock()
		g.log.Warn("Could not record use of API key", "key_id", keyID, "error", err.Error())
	}
}

// verifyTurn is _validate_turn_token: the turn must be live and the person
// it acts under still a member of the workspace.
func (g *Gate) verifyTurn(ctx context.Context, token string) (port.Principal, bool, error) {
	claims, ok, err := decodeTurn(token, g.turnKey, unixSeconds(g.now()))
	if err != nil || !ok {
		return port.Principal{}, false, err
	}
	if g.live == nil {
		return port.Principal{}, false, errors.New("live runner turns are kept in Redis; none is configured")
	}
	alive, err := g.live.Alive(ctx, claims.TurnID)
	if err != nil {
		return port.Principal{}, false, err
	}
	if !alive {
		g.log.Info("Refused the token of a turn that is over", "turn_id", claims.TurnID, "task_id", claims.TaskID)
		return port.Principal{}, false, nil
	}
	agent := claims.ActorType == port.SubjectAgent
	userID := claims.ActorID
	if agent {
		userID = claims.OnBehalfOf
	}
	owned, err := g.ownsWorkspace(ctx, userID, claims.WorkspaceID)
	if err != nil {
		return port.Principal{}, false, err
	}
	if !owned && !g.hasGraphMembership(ctx, userID, claims.WorkspaceID) {
		g.log.Warn("Turn token refused: its user is not a member of the workspace",
			"turn_id", claims.TurnID, "task_id", claims.TaskID, "user_id", userID, "workspace_id", claims.WorkspaceID)
		return port.Principal{}, false, nil
	}
	if userID == "" {
		return port.Principal{}, false, port.ErrNoPrincipal
	}
	p := port.Principal{
		UserID:           userID,
		BoundWorkspaceID: claims.WorkspaceID,
		BoundTaskID:      claims.TaskID,
		TurnClientID:     claims.ClientID,
		Credential:       &port.Credential{Kind: port.KindTurn, KeyID: claims.TurnID, Surface: port.SurfaceAPI},
	}
	if agent {
		p.Subject = &port.Subject{Kind: port.SubjectAgent, ID: claims.ActorID}
	}
	return p, true, nil
}

// memberWorkspaceIDs is _member_workspace_ids: a graph outage narrows reach
// to owned workspaces instead of failing the request.
func (g *Gate) memberWorkspaceIDs(ctx context.Context, userID string) []string {
	tuples, err := g.graph.Read(ctx, authz.Query{Type: "Workspace", Relation: "members", User: userSubject(userID)})
	if err != nil {
		g.log.Warn("Could not resolve workspace memberships", "user_id", userID, "error", err.Error())
		return nil
	}
	out := make([]string, 0, len(tuples))
	for _, t := range tuples {
		if t.ObjectType() == "Workspace" && t.Relation == "members" {
			out = append(out, t.ObjectID())
		}
	}
	slices.Sort(out)
	return slices.Compact(out)
}

// ownedAndNamed is _owned_and_named_workspaces; database errors propagate.
func (g *Gate) ownedAndNamed(ctx context.Context, userID, slug, id string) ([]Workspace, *Workspace, error) {
	rows, err := g.store.OwnedOrNamed(ctx, userID, slug, id)
	if err != nil {
		return nil, nil, err
	}
	var owned []Workspace
	var named *Workspace
	for i, w := range rows {
		if w.OwnerUserID == userID {
			owned = append(owned, w)
		}
		if named == nil && ((slug != "" && w.Slug == slug) || (id != "" && w.ID == id)) {
			named = &rows[i]
		}
	}
	return owned, named, nil
}

// resolveAccess is _resolve_access: fills p's reach and returns the
// workspace slug or id names, reachable or not.
func (g *Gate) resolveAccess(ctx context.Context, p *port.Principal, slug, id string) (*Workspace, error) {
	if p.BoundTaskID != "" {
		_, named, err := g.ownedAndNamed(ctx, p.UserID, slug, id)
		if err != nil {
			return nil, err
		}
		p.AccessibleWorkspaces = []string{p.BoundWorkspaceID}
		p.AdminWorkspaces = []string{}
		return named, nil
	}
	accessible := []string{}
	if g.reach != nil {
		extra, err := g.reach.AccessibleWorkspaces(ctx, *p)
		if err != nil {
			return nil, err
		}
		accessible = append(accessible, extra...)
	}
	for _, m := range g.memberWorkspaceIDs(ctx, p.UserID) {
		if !slices.Contains(accessible, m) {
			accessible = append(accessible, m)
		}
	}
	owned, named, err := g.ownedAndNamed(ctx, p.UserID, slug, id)
	if err != nil {
		return nil, err
	}
	administered := make([]string, 0, len(owned))
	for _, w := range owned {
		administered = append(administered, w.ID)
		if !slices.Contains(accessible, w.ID) {
			accessible = append(accessible, w.ID)
		}
	}
	if p.BoundWorkspaceID != "" {
		keep := func(ids []string) []string {
			out := []string{}
			for _, w := range ids {
				if w == p.BoundWorkspaceID {
					out = append(out, w)
				}
			}
			return out
		}
		accessible, administered = keep(accessible), keep(administered)
	}
	if p.BoundAgentID != "" || p.BoundClientID != "" {
		accessible, administered = []string{}, []string{}
	}
	p.AccessibleWorkspaces, p.AdminWorkspaces = accessible, administered
	return named, nil
}

func refuseBound(p port.Principal) error {
	switch {
	case p.BoundAgentID != "":
		return forbidden(port.DetailAgentKeyRefused)
	case p.BoundClientID != "":
		return forbidden(port.DetailRunnerKeyRefused)
	case p.BoundTaskID != "":
		return forbidden(port.DetailTurnTokenRefused)
	}
	return nil
}

// Principal is get_principal.
func (g *Gate) Principal(ctx context.Context, p port.Principal) (port.Principal, error) {
	if err := refuseBound(p); err != nil {
		return port.Principal{}, err
	}
	if _, err := g.resolveAccess(ctx, &p, "", ""); err != nil {
		return port.Principal{}, err
	}
	return p, nil
}

func (g *Gate) forbiddenWorkspace(p port.Principal, reference string) error {
	g.log.Warn("Rejected workspace selection", "user_id", p.UserID, "requested", reference, "accessible", p.AccessibleWorkspaces)
	return forbidden(port.DetailNotAMember)
}

// admitBoundKey is _admit_agent_key and _admit_runner_key: the key acts in
// its workspace only on a request bound to its agent or client.
func admitBoundKey(p *port.Principal, b *port.Binding, agent bool) error {
	bound, refused := p.BoundClientID, port.DetailRunnerKeyRefused
	if agent {
		bound, refused = p.BoundAgentID, port.DetailAgentKeyRefused
	}
	if b == nil || b.WorkspaceID != p.BoundWorkspaceID {
		return forbidden(refused)
	}
	if (agent && b.AgentID != bound) || (!agent && b.ClientID != bound) {
		return forbidden(refused)
	}
	p.AccessibleWorkspaces = []string{b.WorkspaceID}
	p.AdminWorkspaces = []string{}
	return nil
}

// Caller is get_user_context.
func (g *Gate) Caller(ctx context.Context, p port.Principal, route port.Route) (port.Caller, error) {
	binding := route.Binding
	if route.HasWorkspaceRef {
		binding = nil
	}
	if p.BoundAgentID != "" {
		if err := admitBoundKey(&p, binding, true); err != nil {
			return port.Caller{}, err
		}
	}
	if p.BoundClientID != "" {
		if err := admitBoundKey(&p, binding, false); err != nil {
			return port.Caller{}, err
		}
	}
	if p.BoundTaskID != "" && (!route.AdmitsTurnToken || route.TaskID != p.BoundTaskID) {
		return port.Caller{}, forbidden(port.DetailTurnTokenRefused)
	}
	var workspaceID, workspaceSlug string
	if route.HasWorkspaceRef {
		ref := route.WorkspaceRef
		if !scope.ValidWorkspaceSlug(ref) {
			return port.Caller{}, &port.Error{Status: http.StatusUnprocessableEntity, Detail: port.DetailMalformedWorkspace}
		}
		slug, id := ref, ""
		if scope.IsUUIDShaped(ref) {
			slug, id = "", ref
		}
		named, err := g.resolveAccess(ctx, &p, slug, id)
		if err != nil {
			return port.Caller{}, err
		}
		if named == nil {
			return port.Caller{}, g.forbiddenWorkspace(p, ref)
		}
		workspaceID, workspaceSlug = named.ID, named.Slug
	} else {
		if route.Binding == nil {
			return port.Caller{}, port.ErrWorkspaceNotSelected
		}
		if p.AccessibleWorkspaces == nil {
			if _, err := g.resolveAccess(ctx, &p, "", ""); err != nil {
				return port.Caller{}, err
			}
		}
		workspaceID, workspaceSlug = route.Binding.WorkspaceID, route.Binding.WorkspaceSlug
	}
	ws, err := scope.NewWorkspace(workspaceID, workspaceSlug)
	if err != nil {
		return port.Caller{}, g.forbiddenWorkspace(p, workspaceSlug)
	}
	caller, err := p.Enter(ws)
	if err != nil {
		var unreachable *scope.UnreachableError
		if errors.As(err, &unreachable) {
			return port.Caller{}, g.forbiddenWorkspace(p, workspaceSlug)
		}
		return port.Caller{}, err
	}
	return caller, nil
}

// Optional is resolve_principal_from_token: refusals read as nobody; only
// internal failures are errors.
func (g *Gate) Optional(ctx context.Context, token string, on port.Surface, admitTurn bool) (*port.Principal, error) {
	if token == "" {
		return nil, nil
	}
	p, err := g.Verify(ctx, token)
	if err != nil {
		var refusal *port.Error
		if errors.As(err, &refusal) {
			g.log.Debug("Token authentication failed", "detail", refusal.Detail)
			return nil, nil
		}
		return nil, err
	}
	if p.Credential != nil && !p.Credential.Reaches(on) {
		g.log.Info("Refused an OAuth token not granted this surface", "surface", on, "granted", p.Credential.Granted)
		return nil, nil
	}
	if p.BoundClientID != "" {
		g.log.Info("Refused a runner's key here", "client_id", p.BoundClientID)
		return nil, nil
	}
	if p.BoundTaskID != "" && !admitTurn {
		g.log.Info("Refused the token of a turn here", "task_id", p.BoundTaskID)
		return nil, nil
	}
	if _, err := g.resolveAccess(ctx, &p, "", ""); err != nil {
		return nil, err
	}
	return &p, nil
}

// RunnerKey is authenticate_runner_key.
func (g *Gate) RunnerKey(ctx context.Context, token string) (*port.Principal, error) {
	if !strings.HasPrefix(token, port.APIKeyPrefix) {
		return nil, nil
	}
	p, ok, err := g.verifyAPIKey(ctx, token)
	if err != nil {
		return nil, err
	}
	if !ok || p.BoundClientID == "" {
		return nil, nil
	}
	return &p, nil
}

// EnterAsRunner is enter_as_runner.
func (g *Gate) EnterAsRunner(p port.Principal, ws scope.Workspace) (port.Caller, error) {
	binding := &port.Binding{WorkspaceID: ws.ID(), WorkspaceSlug: ws.Slug(), ClientID: p.BoundClientID}
	if err := admitBoundKey(&p, binding, false); err != nil {
		return port.Caller{}, err
	}
	return p.Enter(ws)
}

// EnterWorkspace is enter_workspace: a UUID-shaped reference is looked up as
// an id only, anything else as a slug only; unknown and foreign workspaces
// are refused alike.
func (g *Gate) EnterWorkspace(ctx context.Context, p port.Principal, reference string) (port.Caller, error) {
	if p.AccessibleWorkspaces == nil {
		if _, err := g.resolveAccess(ctx, &p, "", ""); err != nil {
			return port.Caller{}, err
		}
	}
	var row Workspace
	var found bool
	var err error
	if scope.IsUUIDShaped(reference) {
		row, found, err = g.store.WorkspaceByID(ctx, reference)
	} else {
		row, found, err = g.store.WorkspaceBySlug(ctx, reference)
	}
	if err != nil {
		return port.Caller{}, fmt.Errorf("load workspace %q: %w", reference, err)
	}
	if !found {
		return port.Caller{}, &scope.UnreachableError{Reference: reference}
	}
	ws, err := scope.NewWorkspace(row.ID, row.Slug)
	if err != nil {
		return port.Caller{}, &scope.UnreachableError{Reference: reference}
	}
	return p.Enter(ws)
}
