// Package authn says who a call is made as and what it authenticated with.
//
// Authentication settles both once, at the edge (auth/dependencies.py):
// Kratos session JWTs, Hydra OAuth JWTs (the MCP authorization flow and the
// CLI; client-credentials tokens are refused), workspace API keys, agent keys
// (A2A), runner keys and turn tokens (ADR-0051). A principal is never inferred: either a real user
// authenticated, or platform infrastructure declared itself.
//
// Values here mirror auth/context.py and auth/credential.py; the verifiers are
// ports, implemented by the cluster profile.
package authn

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Scope is what a credential may do beyond its principal's roles.
type Scope string

const (
	// ScopeCredentials: mint or revoke API keys, link a messenger account.
	ScopeCredentials Scope = "credentials"
	// ScopeWorkspaces: create or join a workspace.
	ScopeWorkspaces Scope = "workspaces"
)

// CredentialKind is what a request authenticated with.
type CredentialKind string

const (
	KindSession CredentialKind = "session"
	KindOAuth   CredentialKind = "oauth"
	KindAPIKey  CredentialKind = "api_key"
	KindTurn    CredentialKind = "turn"
)

// Surface is where the request came in.
type Surface string

const (
	SurfaceAPI Surface = "api"
	SurfaceMCP Surface = "mcp"
)

// OAuth scopes a user grants a client (ADR-0058).
const (
	// OAuthScopeMCP reaches MCP only, in the one workspace the token names.
	OAuthScopeMCP = "mcp"
	// OAuthScopeAPI reaches the whole account; first-party clients only.
	OAuthScopeAPI = "api"
)

// FirstPartyClientIDs are the OAuth clients the platform registers itself;
// only a token issued to one of them may carry OAuthScopeAPI (ADR-0058).
func FirstPartyClientIDs() []string { return []string{"agentarea-cli", "agentarea-desktop"} }

// Credential is how a request authenticated, and on which surface. KeyID is
// the API key's id for api_key and the turn's id for turn. Granted is the
// OAuth scopes an oauth token carries.
type Credential struct {
	Kind    CredentialKind
	KeyID   string
	Surface Surface
	Granted []string
}

// Scopes granted per kind; a kind without an entry is granted nothing.
func (c Credential) Scopes() []Scope {
	switch c.Kind {
	case KindSession:
		return []Scope{ScopeCredentials, ScopeWorkspaces}
	case KindOAuth:
		if slices.Contains(c.Granted, OAuthScopeAPI) {
			return []Scope{ScopeCredentials, ScopeWorkspaces}
		}
		return nil
	case KindAPIKey, KindTurn:
		return nil
	}
	return nil
}

// Reaches reports whether the credential may be used on surface s: an oauth
// token needs api, or mcp on the MCP surface.
func (c Credential) Reaches(s Surface) bool {
	if c.Kind != KindOAuth {
		return true
	}
	return slices.Contains(c.Granted, OAuthScopeAPI) || (s == SurfaceMCP && slices.Contains(c.Granted, OAuthScopeMCP))
}

// Grants reports whether the credential grants s.
func (c Credential) Grants(s Scope) bool { return slices.Contains(c.Scopes(), s) }

// SubjectKind is who the authorization graph is asked about.
type SubjectKind string

const (
	SubjectUser  SubjectKind = "user"
	SubjectAgent SubjectKind = "agent"
)

// Subject is a person, or the agent a run executes as.
type Subject struct {
	Kind SubjectKind
	ID   string
}

// GraphSubject is the graph reference: "User:<id>" or "Agent:<id>".
func (s Subject) GraphSubject() string {
	if s.Kind == SubjectAgent {
		return "Agent:" + s.ID
	}
	return "User:" + s.ID
}

// Principal is an authenticated caller before a workspace is selected
// (UserPrincipal). Authentication says who is calling, never where; Enter is
// the only way to a Caller.
type Principal struct {
	UserID   string
	Email    string
	ClientID string
	// BoundWorkspaceID: an API key acts only in the workspace it was issued for.
	BoundWorkspaceID string
	// GrantedWorkspaceIDs: an OAuth mcp token acts only in the workspaces its
	// consent named; nil when the credential is not narrowed this way.
	GrantedWorkspaceIDs []string
	// BoundAgentID: an agent's key reaches that one agent over A2A and no workspace.
	BoundAgentID string
	// BoundClientID: a runner's key reaches only its client's runner routes.
	BoundClientID string
	// BoundTaskID: a turn's token reaches its client's MCP bundle and its own task's files.
	BoundTaskID string
	// TurnClientID: the client whose runner holds the turn.
	TurnClientID string
	// Subject is the turn's agent when a turn acts as it; nil means the user.
	Subject    *Subject
	Credential *Credential
	// AccessibleWorkspaces is nil until resolved per request; empty means none.
	AccessibleWorkspaces []string
	// AdminWorkspaces is nil until resolved; nil denies rather than allows.
	AdminWorkspaces []string
}

// GraphSubject is the subject's graph reference, the user's when none is set.
func (p Principal) GraphSubject() string {
	if p.Subject != nil {
		return p.Subject.GraphSubject()
	}
	return Subject{Kind: SubjectUser, ID: p.UserID}.GraphSubject()
}

// ActsAsAgent reports whether a run acts through this principal: UserID is
// then only the person who started it, whose rights bound the agent and never
// pass to it.
func (p Principal) ActsAsAgent() bool {
	return p.Subject != nil && p.Subject.Kind == SubjectAgent
}

// Enter returns the Caller acting in ws, which must be accessible.
func (p Principal) Enter(ws scope.Workspace) (Caller, error) {
	if p.UserID == "" {
		return Caller{}, ErrNoPrincipal
	}
	if ws.IsZero() || !slices.Contains(p.AccessibleWorkspaces, ws.ID()) {
		return Caller{}, &scope.UnreachableError{Reference: ws.Slug()}
	}
	p.AccessibleWorkspaces = slices.Clone(p.AccessibleWorkspaces)
	p.AdminWorkspaces = slices.Clone(p.AdminWorkspaces)
	return Caller{Principal: p, Workspace: ws}, nil
}

// Caller is a principal acting in one workspace (UserContext).
type Caller struct {
	Principal
	Workspace scope.Workspace
}

// ErrNoPrincipal refuses a principal or caller that names nobody.
var ErrNoPrincipal = errors.New("user_id is required; refusing to act without a principal")

// ErrUnauthenticated is a request without valid credentials (401).
var ErrUnauthenticated = errors.New("not authenticated")

// ScopeRequiredError: the credential lacks a scope the action needs, whatever
// the principal's roles. Action completes "This credential cannot ...".
type ScopeRequiredError struct {
	Scope  Scope
	Action string
}

func (e *ScopeRequiredError) Error() string {
	return "This credential cannot " + e.Action + "; sign in as a user to do it"
}

// EnsureScope refuses action unless p's credential grants s.
func EnsureScope(p Principal, s Scope, action string) error {
	if p.Credential == nil || !p.Credential.Grants(s) {
		return &ScopeRequiredError{Scope: s, Action: action}
	}
	return nil
}

// Error is a refusal with the status and detail Python's HTTPException
// carries; httpx renders it as problem+json with code http_error and sets
// WWW-Authenticate when it is not empty. 401s match ErrUnauthenticated.
type Error struct {
	Status          int
	Detail          string
	WWWAuthenticate string
}

func (e *Error) Error() string { return e.Detail }

// Is makes every 401 match ErrUnauthenticated.
func (e *Error) Is(target error) bool {
	return target == ErrUnauthenticated && e.Status == http.StatusUnauthorized
}

// Details of the refusals; the strings are contract (tests and the web app read them).
const (
	DetailMissingCredentials = "Missing authentication credentials"
	DetailTurnEnded          = "The turn this token was issued for has ended"
	DetailInvalidAPIKey      = "Invalid or expired API key"
	DetailInvalidToken       = "Invalid authentication token"
	DetailAuthInternal       = "Internal server error during authentication"
	DetailAgentKeyRefused    = "This key reaches only its agent, over A2A"
	DetailRunnerKeyRefused   = "This key reaches only its client's runner routes"
	DetailTurnTokenRefused   = "This token reaches only its client's tools and task files"
	DetailNotAMember         = "User is not a member of the requested workspace"
	DetailMalformedWorkspace = "Malformed workspace reference in the path"
	DetailInsufficientScope  = "This OAuth token was not granted access to this API"
)

// Challenge is the WWW-Authenticate value of every 401 (RFC 9728), with the
// API's public URL (AGENTAREA_API_URL).
func Challenge(apiURL string) string {
	return `Bearer resource_metadata="` + strings.TrimRight(apiURL, "/") + `/.well-known/oauth-protected-resource"`
}

// ErrWorkspaceNotSelected: a workspace route names no workspace and binds
// none; a routing bug, answered 500 (WorkspaceNotSelectedError).
var ErrWorkspaceNotSelected = errors.New("needs a workspace context but names no workspace and binds none")

// BearerToken is the credential of an "Authorization: <scheme> <token>"
// header whose scheme is bearer in any case, as FastAPI's HTTPBearer reads
// it; ok is false when there is none.
func BearerToken(r *http.Request) (string, bool) {
	header := r.Header.Get("Authorization")
	if header == "" {
		return "", false
	}
	scheme, param, _ := strings.Cut(header, " ")
	token := trimPythonSpace(param)
	if scheme == "" || token == "" || !strings.EqualFold(scheme, "bearer") {
		return "", false
	}
	return token, true
}

// trimPythonSpace is str.strip() over a header value Starlette decodes as latin-1.
func trimPythonSpace(s string) string {
	isSpace := func(c byte) bool {
		return (c >= 0x09 && c <= 0x0d) || (c >= 0x1c && c <= 0x20) || c == 0x85 || c == 0xa0
	}
	start, end := 0, len(s)
	for start < end && isSpace(s[start]) {
		start++
	}
	for end > start && isSpace(s[end-1]) {
		end--
	}
	return s[start:end]
}

// APIKeyPrefix starts every API key, of every flavour (workspace, agent, runner).
const APIKeyPrefix = "aat_"

// APIKeyPrefixLength is how much of a key is stored in clear as token_prefix.
const APIKeyPrefixLength = 12

// HashAPIKey is the api_keys.token_hash of token: sha256 hex of its UTF-8
// bytes, the header value read as latin-1 as Starlette does.
func HashAPIKey(token string) string {
	sum := sha256.Sum256([]byte(latin1ToUTF8(token)))
	return hex.EncodeToString(sum[:])
}

func latin1ToUTF8(s string) string {
	ascii := true
	for i := range len(s) {
		if s[i] >= 0x80 {
			ascii = false
			break
		}
	}
	if ascii {
		return s
	}
	runes := make([]rune, len(s))
	for i := range len(s) {
		runes[i] = rune(s[i])
	}
	return string(runes)
}

// NewAPIKey mints a key as access_token_service.py does: the prefix and
// token_urlsafe(32), its stored prefix and its hash.
func NewAPIKey() (token, prefix, hash string, err error) {
	raw := make([]byte, 32)
	if _, err = rand.Read(raw); err != nil {
		return "", "", "", err
	}
	token = APIKeyPrefix + base64.RawURLEncoding.EncodeToString(raw)
	return token, token[:APIKeyPrefixLength], HashAPIKey(token), nil
}

// Authenticator resolves the principal of an HTTP request from its
// Authorization bearer token (no cookie, header or query is read), or returns
// an *Error. Workspace selection is not its job.
type Authenticator interface {
	Authenticate(ctx context.Context, r *http.Request) (Principal, error)
}

// Binding is the workspace an id-addressed route selected from the entity it
// addresses (bind_request_workspace); AgentID and ClientID name the agent or
// client it was bound for, where only that agent's or client's key may act.
type Binding struct {
	WorkspaceID   string
	WorkspaceSlug string
	AgentID       string
	ClientID      string
}

// Route is what a workspace route tells admission about the request.
type Route struct {
	// WorkspaceRef is the {workspace} path parameter; HasWorkspaceRef is
	// false on a route that has none.
	WorkspaceRef    string
	HasWorkspaceRef bool
	// Binding is set by a binds_workspace dependency that ran before.
	Binding *Binding
	// AdmitsTurnToken marks a route of one task a turn of that task may call
	// (admits_turn_token); TaskID is its task_id path parameter.
	AdmitsTurnToken bool
	TaskID          string
}

// Gate authenticates and admits callers (auth/dependencies.py). Every method
// refuses with *Error (an HTTPException in Python); any other error is an
// internal failure (500).
type Gate interface {
	Authenticator
	// Verify resolves a bearer token to its principal (_verify_token).
	Verify(ctx context.Context, token string) (Principal, error)
	// Principal admits p on a route that acts on no single workspace and
	// resolves its reach (get_principal).
	Principal(ctx context.Context, p Principal) (Principal, error)
	// Caller admits p into the workspace the route selects (get_user_context).
	Caller(ctx context.Context, p Principal, route Route) (Caller, error)
	// Optional is the principal of token on an optional-auth edge (A2A, the
	// MCP mounts), nil when there is none or it is refused
	// (resolve_principal_from_token); only admitTurn lets a turn's token in.
	Optional(ctx context.Context, token string, on Surface, admitTurn bool) (*Principal, error)
	// RunnerKey is the principal of a client's runner key, nil for any other
	// token (authenticate_runner_key).
	RunnerKey(ctx context.Context, token string) (*Principal, error)
	// EnterAsRunner is a runner key's caller in its client's workspace.
	EnterAsRunner(p Principal, ws scope.Workspace) (Caller, error)
	// EnterWorkspace is p acting in the workspace reference names by slug or
	// id, for the MCP surfaces (enter_workspace).
	EnterWorkspace(ctx context.Context, p Principal, reference string) (Caller, error)
}

// TurnClaims is what a turn's token says: who acts, through which client, on
// which task (auth/turn_token.py).
type TurnClaims struct {
	TurnID      string
	TaskID      string
	WorkspaceID string
	ClientID    string
	ActorType   SubjectKind
	ActorID     string
	// OnBehalfOf is the person the task is attributed to.
	OnBehalfOf string
}

// TurnTokens issues and decodes turn tokens with the same signing key and
// encoding as Python, so either backend accepts the other's tokens.
type TurnTokens interface {
	Issue(claims TurnClaims, ttl time.Duration) (string, error)
	// Decode returns false for a token that is not a valid, unexpired turn token.
	Decode(token string) (TurnClaims, bool)
}

// LiveTurns tracks which turns are running (Redis keys runners:live-turn:<id>);
// a turn token is honoured only while its turn is alive.
type LiveTurns interface {
	Begin(ctx context.Context, turnID string, ttl time.Duration) error
	Renew(ctx context.Context, turnID string, ttl time.Duration) error
	End(ctx context.Context, turnID string) error
	Alive(ctx context.Context, turnID string) (bool, error)
}

type principalKey struct{}

type callerKey struct{}

// WithPrincipal stores the authenticated principal in ctx.
func WithPrincipal(ctx context.Context, p Principal) context.Context {
	return context.WithValue(ctx, principalKey{}, p)
}

// PrincipalFrom returns the principal stored by WithPrincipal.
func PrincipalFrom(ctx context.Context) (Principal, bool) {
	p, ok := ctx.Value(principalKey{}).(Principal)
	return p, ok
}

// WithCaller stores the caller of a workspace route in ctx.
func WithCaller(ctx context.Context, c Caller) context.Context {
	return context.WithValue(ctx, callerKey{}, c)
}

// CallerFrom returns the caller stored by WithCaller.
func CallerFrom(ctx context.Context) (Caller, bool) {
	c, ok := ctx.Value(callerKey{}).(Caller)
	return c, ok
}
