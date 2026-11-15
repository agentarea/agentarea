package service

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/mcpclient"
)

// CallerContext is who a call through an instance is for: the signed
// X-AgentArea-Context claims (caller form or run form).
type CallerContext struct {
	UserID, UserEmail, ClientID string
	TaskID, ToolCallID, AgentID string
	EndUserID                   string
	Metadata                    map[string]any
	// Tool is the single tools/call this request carries; empty otherwise.
	Tool string
}

// Upstream is where a request to an instance goes and what it carries.
type Upstream struct {
	URL       string
	Transport http.RoundTripper
	// Headers are the instance's own (plain, referenced, stored secret), the
	// auth config's and the signed context; set them on the outbound request.
	Headers http.Header
	// Gateway marks the in-process demand gateway (container transports).
	Gateway bool
}

// UpstreamAuthError is a credential of the instance that could not be read
// for a proxied request (Python's 502 "Upstream auth failed").
type UpstreamAuthError struct{ Err error }

func (e *UpstreamAuthError) Error() string { return "Upstream auth failed" }
func (e *UpstreamAuthError) Unwrap() error { return e.Err }

// Context signing (tool_context.py).
const (
	ContextHeader       = "X-AgentArea-Context"
	contextProtocol     = "1"
	contextIssuer       = "agentarea"
	contextTokenTTL     = 300 * time.Second
	contextMetaPrefix   = "agentarea/"
	contextDerivation   = "agentarea/mcp-context/v1:"
	gatewayBase         = "http://mcp-gateway.internal"
	errNoUpstreamURL    = "Instance has no resolvable upstream MCP URL"
	errGatewayNotConfig = "MCP demand gateway is not configured"
)

// DerivedContextKey is a platform-run instance's signing key: hex
// HMAC-SHA256 of its id under the gateway secret (the runtime's MCP_CONTEXT_KEY).
func DerivedContextKey(gatewaySecret, instanceID string) string {
	m := hmac.New(sha256.New, []byte(gatewaySecret))
	m.Write([]byte(contextDerivation + instanceID))
	return hex.EncodeToString(m.Sum(nil))
}

// contextValues is the claims of a context, absent optional fields left out.
func contextValues(workspaceID string, cc CallerContext) map[string]any {
	v := map[string]any{"protocol": contextProtocol, "workspace_id": workspaceID}
	if cc.TaskID != "" {
		v["task_id"] = cc.TaskID
		v["tool_call_id"] = cc.ToolCallID
		v["idempotency_key"] = cc.TaskID + ":" + cc.ToolCallID
		if cc.AgentID != "" {
			v["agent_id"] = cc.AgentID
		}
		if cc.EndUserID != "" {
			v["end_user_id"] = cc.EndUserID
		}
		if len(cc.Metadata) > 0 {
			v["metadata"] = cc.Metadata
		}
		return v
	}
	v["user_id"] = cc.UserID
	if cc.UserEmail != "" {
		v["user_email"] = cc.UserEmail
	}
	if cc.ClientID != "" {
		v["client_id"] = cc.ClientID
	}
	return v
}

// contextMeta is the agentarea/* keys of params._meta.
func contextMeta(workspaceID string, cc CallerContext) map[string]any {
	out := map[string]any{}
	for k, v := range contextValues(workspaceID, cc) {
		out[contextMetaPrefix+k] = v
	}
	return out
}

// SignContext mints the X-AgentArea-Context token for one call to one
// instance (aud) and, when known, one tool.
func SignContext(workspaceID string, cc CallerContext, key, instanceID, tool string, now time.Time) (string, error) {
	claims := jwt.MapClaims{}
	for k, v := range contextValues(workspaceID, cc) {
		claims[k] = v
	}
	iat := now.Unix()
	claims["iss"] = contextIssuer
	claims["aud"] = instanceID
	claims["iat"] = iat
	claims["exp"] = iat + int64(contextTokenTTL/time.Second)
	claims["jti"] = uuid.NewString()
	if tool != "" {
		claims["tool"] = tool
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(key))
}

func contextEnabled(spec map[string]any) bool {
	m, ok := spec[domain.ContextSpecKey].(map[string]any)
	return ok && m["enabled"] == true
}

// target is what an instance connects with.
type target struct {
	spec      map[string]any
	url       string
	transport http.RoundTripper
	// declared is the remote transport the spec declares; "" probes.
	declared string
	gateway  bool
	// member: the address is a member's choice, dialled pinned.
	member bool
}

// serverSpec is the instance's spec row; false when it is gone.
func (s *Service) serverSpec(ctx context.Context, ws scope.Workspace, inst domain.Instance) (catalogapi.MCPSpec, bool, error) {
	if s.d.Specs == nil {
		return catalogapi.MCPSpec{}, false, &domain.Unavailable{Msg: "MCP server specs are not available"}
	}
	return s.d.Specs.Get(ctx, ws, inst.ServerSpecID, catalogapi.MCPSpecGet{PlatformBacked: inst.PlatformManaged()})
}

// transportSpec is instance_transport_spec.
func transportSpec(spec catalogapi.MCPSpec, inst domain.Instance) map[string]any {
	return domain.MergeTransportSpec(
		domain.ServerTransportSpec(spec.JSONSpec, spec.RemoteURL, spec.Cmd, spec.DockerImageURL),
		inst.JSONSpec, inst.Transport)
}

// declaredRemoteTransport is the remotes[].type a registry spec declares.
func declaredRemoteTransport(spec map[string]any) string {
	remotes, _ := spec["remotes"].([]any)
	for _, r := range remotes {
		if m, ok := r.(map[string]any); ok {
			if t, ok := m["type"].(string); ok && t != "" {
				return t
			}
		}
	}
	return ""
}

func gatewayURL(id string) string { return gatewayBase + "/mcp/" + id + "/mcp" }

// targetOf resolves where calls to inst go, given its merged spec.
func (s *Service) targetOf(inst domain.Instance, spec map[string]any) (target, error) {
	t := target{spec: spec}
	switch {
	case domain.IsContainer(inst.Transport):
		if s.d.Runtime == nil {
			return t, &domain.Unavailable{Msg: errGatewayNotConfig}
		}
		t.url, t.gateway, t.declared = gatewayURL(inst.ID), true, "streamable-http"
		t.transport = mcpclient.GatewayRetry(mcpclient.HandlerTransport(s.d.Runtime.Gateway()), mcpclient.GatewayStartWait)
	case inst.Transport == domain.TransportURL:
		if s.d.Out == nil {
			return t, &domain.Unavailable{Msg: "outbound HTTP is not configured"}
		}
		t.url, _ = spec["endpoint_url"].(string)
		t.declared = declaredRemoteTransport(spec)
		if inst.PlatformManaged() {
			t.transport = mcpclient.GatewayRetry(s.d.Out.Transport(netguard.Internal), mcpclient.GatewayStartWait)
		} else {
			t.member, t.transport = true, s.d.Out.Transport(netguard.Member)
		}
	default:
		return t, &domain.Invalid{Msg: "bundle has no endpoint_url"}
	}
	return t, nil
}

// secretUnresolved is SecretRefUnresolvedError: a header reference that
// cannot be read now.
type secretUnresolved struct{ msg string }

func (e *secretUnresolved) Error() string { return e.msg }

// instanceSecrets reads names of the instance's secret slots, from the
// platform workspace for a platform-managed connection. Absent ones are skipped.
func (s *Service) instanceSecrets(ctx context.Context, inst domain.Instance, names []string) (map[string]string, error) {
	out := map[string]string{}
	if len(names) == 0 {
		return out, nil
	}
	if s.d.Secrets == nil {
		return nil, &domain.Unavailable{Msg: "the secret store is not configured"}
	}
	ws := PlatformWorkspace()
	if !inst.PlatformManaged() {
		var err error
		if ws, err = scope.NewWorkspace(inst.WorkspaceID, ""); err != nil {
			return nil, err
		}
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	m := s.d.Secrets.Manager(sess, inst.CreatedBy)
	for _, n := range names {
		v, err := m.Get(ctx, domain.InstanceSecretName(inst.ID, n))
		if errors.Is(err, ksecrets.ErrNotFound) {
			continue
		}
		if err != nil {
			return nil, err
		}
		out[n] = v
	}
	return out, nil
}

// referencedHeaders is _referenced_headers: the header values the instance
// references, read now from its workspace's secrets.
func (s *Service) referencedHeaders(ctx context.Context, ws scope.Workspace, inst domain.Instance) (map[string]string, error) {
	headers, _ := inst.JSONSpec["headers"].(map[string]any)
	refs, err := domain.SpecSecretRefs(map[string]any{"headers": headers})
	if err != nil || len(refs) == 0 {
		return map[string]string{}, err
	}
	if inst.WorkspaceID != ws.ID() {
		return nil, &secretUnresolved{fmt.Sprintf("MCP instance %s is not in the workspace reading its secrets", inst.ID)}
	}
	if s.d.Secrets == nil {
		return nil, &domain.Unavailable{Msg: "the secret store is not configured"}
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	m := s.d.Secrets.Manager(sess, inst.CreatedBy)
	out := map[string]string{}
	for name, secret := range refs {
		if ksecrets.ReservedPrefix(secret) != "" {
			return nil, &secretUnresolved{fmt.Sprintf("Header %s of MCP instance %s references secret '%s', "+
				"a platform-reserved name no reference may read", name, inst.ID, secret)}
		}
		v, err := m.Get(ctx, secret)
		if err != nil && !errors.Is(err, ksecrets.ErrNotFound) {
			return nil, err
		}
		if v == "" {
			return nil, &secretUnresolved{fmt.Sprintf("Header %s of MCP instance %s references secret '%s', "+
				"which has no value in its workspace", name, inst.ID, secret)}
		}
		out[name] = v
	}
	return out, nil
}

// secretHeaders is _secret_headers: a URL connection's referenced and stored
// secret headers (it has no environment, so every secret is a header).
func (s *Service) secretHeaders(ctx context.Context, ws scope.Workspace, inst domain.Instance) (map[string]string, error) {
	if inst.Transport != domain.TransportURL {
		return map[string]string{}, nil
	}
	if inst.PlatformManaged() {
		return s.instanceSecrets(ctx, inst, inst.EnvVars())
	}
	headers, err := s.referencedHeaders(ctx, ws, inst)
	if err != nil {
		return nil, err
	}
	stored, err := s.instanceSecrets(ctx, inst, inst.EnvVars())
	if err != nil {
		return nil, err
	}
	for k, v := range stored {
		headers[k] = v
	}
	return headers, nil
}

// plainHeaders is the merged spec's literal header values.
func plainHeaders(spec map[string]any) map[string]string {
	out := map[string]string{}
	if h, ok := spec["headers"].(map[string]any); ok {
		for k, v := range h {
			if str, ok := v.(string); ok {
				out[k] = str
			}
		}
	}
	return out
}

// authHeaders is _resolve_auth_headers: the auth config's headers for
// destination. Reauth and a managed credential asked for another origin are
// errors; any other failure sends no auth header.
func (s *Service) authHeaders(ctx context.Context, ws scope.Workspace, inst domain.Instance, destination string, force bool) (map[string]string, error) {
	if inst.AuthConfigID == nil {
		return map[string]string{}, nil
	}
	id, err := uuid.Parse(*inst.AuthConfigID)
	if err != nil {
		return map[string]string{}, nil
	}
	h, err := s.AuthHeaders(ctx, ws, id, destination, force)
	if err == nil {
		return h, nil
	}
	var reauth *domain.ReauthRequired
	var inv *domain.Invalid
	if errors.As(err, &reauth) || errors.As(err, &inv) {
		return nil, err
	}
	s.d.Log.Warn("Failed to resolve auth headers for instance", "instance_id", inst.ID, "error", err)
	return map[string]string{}, nil
}

// contextKey is the key calls to inst are signed with, "" when it takes no
// caller context: a URL instance's stored secret, a platform-run instance's
// derived key when its spec opts in.
func (s *Service) contextKey(ctx context.Context, inst domain.Instance, spec map[string]any) (string, error) {
	switch {
	case inst.Transport == domain.TransportURL:
		if !domain.Truthy(inst.JSONSpec[domain.ContextSigningFlag]) {
			return "", nil
		}
		got, err := s.instanceSecrets(ctx, inst, []string{domain.ContextSecretEnv})
		if err != nil {
			return "", err
		}
		return got[domain.ContextSecretEnv], nil
	case domain.IsContainer(inst.Transport) && contextEnabled(spec):
		if s.d.Config.GatewaySecret == "" {
			return "", &domain.Unavailable{Msg: errGatewayNotConfig}
		}
		return DerivedContextKey(s.d.Config.GatewaySecret, inst.ID), nil
	}
	return "", nil
}

// contextHeader is the signed header for one call, nil when inst takes none.
func (s *Service) contextHeader(ctx context.Context, ws scope.Workspace, inst domain.Instance, spec map[string]any, cc CallerContext, tool string) (http.Header, error) {
	key, err := s.contextKey(ctx, inst, spec)
	if err != nil || key == "" {
		return nil, err
	}
	token, err := SignContext(ws.ID(), cc, key, inst.ID, tool, s.d.Now())
	if err != nil {
		return nil, err
	}
	h := http.Header{}
	h.Set(ContextHeader, token)
	return h, nil
}

// UpstreamFor resolves an instance's endpoint (url: the merged spec's
// endpoint, SSRF-vetted; docker/command: the runtime gateway) and its
// outbound headers. cc nil sends no context.
func (s *Service) UpstreamFor(ctx context.Context, ws scope.Workspace, inst domain.Instance, cc *CallerContext) (Upstream, error) {
	if inst.Transport == domain.TransportBundle {
		return Upstream{}, &domain.Invalid{Msg: errNoUpstreamURL}
	}
	spec, ok, err := s.serverSpec(ctx, ws, inst)
	if err != nil {
		return Upstream{}, err
	}
	if !ok && inst.Transport == domain.TransportURL {
		return Upstream{}, &domain.Invalid{Msg: errNoUpstreamURL}
	}
	merged := transportSpec(spec, inst)
	t, err := s.targetOf(inst, merged)
	if err != nil {
		return Upstream{}, err
	}
	if t.url == "" {
		return Upstream{}, &domain.Invalid{Msg: errNoUpstreamURL}
	}
	if t.member {
		if _, err := s.d.Out.Guard().CheckURL(ctx, t.url); err != nil {
			s.d.Log.Warn("Rejected SSRF-unsafe MCP upstream", "instance_id", inst.ID, "error", err)
			return Upstream{}, &domain.Invalid{Msg: "Upstream MCP URL is not allowed: " + err.Error()}
		}
	}
	h := http.Header{}
	own, err := s.secretHeaders(ctx, ws, inst)
	if err != nil {
		return Upstream{}, &UpstreamAuthError{Err: err}
	}
	for k, v := range plainHeaders(merged) {
		h.Set(k, v)
	}
	for k, v := range own {
		h.Set(k, v)
	}
	if inst.AuthConfigID != nil {
		id, err := uuid.Parse(*inst.AuthConfigID)
		if err != nil {
			return Upstream{}, &UpstreamAuthError{Err: err}
		}
		auth, err := s.AuthHeaders(ctx, ws, id, t.url, false)
		if err != nil {
			return Upstream{}, &UpstreamAuthError{Err: err}
		}
		for k, v := range auth {
			h.Set(k, v)
		}
	}
	if cc != nil {
		ch, err := s.contextHeader(ctx, ws, inst, merged, *cc, cc.Tool)
		if err != nil {
			return Upstream{}, err
		}
		for k, v := range ch {
			h[k] = v
		}
	}
	return Upstream{URL: t.url, Transport: t.transport, Headers: h, Gateway: t.gateway}, nil
}
