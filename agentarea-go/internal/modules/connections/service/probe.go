package service

import (
	"context"
	"errors"
	"net"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/mcpclient"
)

const (
	validateTimeout = 10 * time.Second
	probeTimeout    = 10 * time.Second
)

// Validation is validate_connection's answer. Tools is set when Valid;
// AuthMethods when the endpoint's auth was classified.
type Validation struct {
	Valid       bool
	Errors      []string
	Tools       []any
	AuthMethods []string
}

// ProbeResult is probe_instance_auth's answer; Status is ok or auth_required.
type ProbeResult struct {
	Status  string
	Methods []string
	Hints   []any
	// HasHints: the credentials branch always carries hints, even empty.
	HasHints bool
}

// ValidateConnection is validate_connection: list tools from url without an
// instance. serverID names the catalog spec being connected; with it, an
// auth failure also reports the spec endpoint's auth methods.
func (s *Service) ValidateConnection(ctx context.Context, ws scope.Workspace, url string, headers map[string]string, serverID string) Validation {
	if url == "" {
		return Validation{Errors: []string{"URL is required"}}
	}
	if s.d.Out == nil {
		return Validation{Errors: []string{"Connection failed. Verify the URL, headers, and server availability."}}
	}
	// The tool list goes back to the caller, so an unguarded URL is a
	// full-read SSRF; the reason stays generic so it is no DNS oracle.
	if _, err := s.d.Out.Guard().CheckURL(ctx, url); err != nil {
		s.d.Log.WarnContext(ctx, "Refused MCP connection validation for a non-public URL", "error", err)
		return Validation{Errors: []string{"URL is not allowed"}}
	}
	h := http.Header{}
	for k, v := range headers {
		h.Set(k, v)
	}
	tools, err := s.listAt(ctx, url, h)
	if err == nil {
		out := Validation{Valid: true, Errors: []string{}, Tools: tools}
		// Listing tools is not using them: an endpoint may list without a
		// token and refuse every call, so a bare one reports its OAuth.
		if len(headers) == 0 {
			if m := s.catalogAuthMethods(ctx, ws, url, serverID); slices.Contains(m, "oauth") {
				out.AuthMethods = m
			}
		}
		return out
	}
	methods := s.catalogAuthMethods(ctx, ws, url, serverID)
	needsAuth := slices.Equal(methods, []string{"oauth", "credentials"}) || slices.Equal(methods, []string{"credentials"})
	status := 0
	var un *mcpclient.UnauthorizedError
	if errors.As(err, &un) {
		status = un.Status
	}
	var he *mcpclient.HTTPError
	if errors.As(err, &he) {
		status = he.Status
	}
	if status == http.StatusForbidden {
		return Validation{Errors: []string{"Access denied — insufficient permissions"}, AuthMethods: orEmpty(methods)}
	}
	if status == http.StatusUnauthorized || needsAuth {
		return Validation{Errors: []string{"Authentication failed — check your credentials"}, AuthMethods: orEmpty(methods)}
	}
	s.d.Log.WarnContext(ctx, "validate_connection failed", "url", url, "error", err)
	return Validation{Errors: []string{"Connection failed. Verify the URL, headers, and server availability."}}
}

// listAt lists url's tools over a pinned member connection.
func (s *Service) listAt(ctx context.Context, url string, h http.Header) ([]any, error) {
	ctx, cancel := context.WithTimeout(ctx, validateTimeout)
	defer cancel()
	c, err := mcpclient.Connect(ctx, mcpclient.Options{URL: url, RoundTripper: s.d.Out.Transport(netguard.Member), Headers: h})
	if err != nil {
		return nil, err
	}
	defer c.Close()
	listed, err := c.ListTools(ctx)
	if err != nil {
		return nil, err
	}
	tools := make([]any, 0, len(listed))
	for _, t := range listed {
		tools = append(tools, mcpclient.SerializeTool(t))
	}
	return tools, nil
}

// catalogAuthMethods is _catalog_auth_methods: only the endpoint the catalog
// spec records is dialled, and only when the caller's url is that endpoint.
func (s *Service) catalogAuthMethods(ctx context.Context, ws scope.Workspace, url, serverID string) []string {
	if serverID == "" || s.d.Specs == nil {
		return nil
	}
	spec, ok, err := s.d.Specs.Get(ctx, ws, serverID, catalogapi.MCPSpecGet{})
	if err != nil {
		s.d.Log.WarnContext(ctx, "Auth-method detection could not read the spec", "server_id", serverID, "error", err)
		return nil
	}
	if !ok || spec.RemoteURL == nil || *spec.RemoteURL == "" || *spec.RemoteURL != url {
		return nil
	}
	return s.detectAuthMethods(ctx, *spec.RemoteURL)
}

// detectAuthMethods is _detect_auth_methods: OAuth from the discovery
// metadata (an endpoint may be POST-only or list without a token), else the
// status of a GET; nil when unclassified.
func (s *Service) detectAuthMethods(ctx context.Context, mcpURL string) []string {
	if _, err := s.d.Out.Guard().CheckURL(ctx, mcpURL); err != nil {
		return nil
	}
	if _, err := s.discoverAuthServer(ctx, mcpURL); err == nil {
		return []string{"oauth", "credentials"}
	}
	status, err := s.getStatus(ctx, mcpURL, false)
	if err != nil {
		return nil
	}
	switch status {
	case http.StatusOK, http.StatusMethodNotAllowed:
		return []string{"none"}
	case http.StatusUnauthorized, http.StatusForbidden:
		return []string{"credentials"}
	}
	return nil
}

func (s *Service) getStatus(ctx context.Context, url string, follow bool) (int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	resp, err := s.httpClient(netguard.Member, probeTimeout, follow).Do(req)
	if err != nil {
		return 0, err
	}
	_ = resp.Body.Close()
	return resp.StatusCode, nil
}

// Probe is probe_instance_auth plus the route's caching of the methods on
// the instance's spec. A refusal is *domain.Invalid (the route's 400).
func (s *Service) Probe(ctx context.Context, ws scope.Workspace, id uuid.UUID) (ProbeResult, error) {
	inst, err := s.instanceIn(ctx, ws, id)
	if err != nil {
		var nf *domain.NotFound
		if errors.As(err, &nf) {
			return ProbeResult{}, &domain.Invalid{Msg: "Instance not found"}
		}
		return ProbeResult{}, err
	}
	if inst.Transport != domain.TransportURL {
		return ProbeResult{}, &domain.Invalid{Msg: "Probe is only supported for URL-type instances"}
	}
	spec, found, err := s.serverSpec(ctx, ws, inst)
	if err != nil {
		return ProbeResult{}, err
	}
	var merged map[string]any
	if found {
		merged = transportSpec(spec, inst)
	} else {
		merged = domain.MergeTransportSpec(nil, inst.JSONSpec, inst.Transport)
	}
	mcpURL, _ := merged["endpoint_url"].(string)
	if mcpURL == "" {
		return ProbeResult{}, &domain.Invalid{Msg: "No endpoint URL configured"}
	}
	r, err := s.probe(ctx, inst, mcpURL, spec, found)
	if err != nil {
		return ProbeResult{}, err
	}
	if len(r.Methods) > 0 && found && s.d.Specs != nil {
		methods := make([]any, len(r.Methods))
		for i, m := range r.Methods {
			methods[i] = m
		}
		ok, err := s.d.Specs.SetAuthMethods(ctx, ws, inst.ServerSpecID, methods)
		switch {
		case err != nil:
			s.d.Log.WarnContext(ctx, "Failed to cache auth methods for MCP server spec after probe", "error", err)
		case !ok:
			s.d.Log.InfoContext(ctx, "Auth methods for MCP server spec not cached: the spec is not owned by the workspace (a shared catalog mirror)",
				"spec_id", inst.ServerSpecID, "workspace_id", ws.ID())
		}
	}
	return r, nil
}

func (s *Service) probe(ctx context.Context, inst domain.Instance, mcpURL string, spec catalogapi.MCPSpec, found bool) (ProbeResult, error) {
	if s.d.Out == nil {
		return ProbeResult{}, &domain.Unavailable{Msg: "outbound HTTP is not configured"}
	}
	if _, err := s.d.Out.Guard().CheckURL(ctx, mcpURL); err != nil {
		s.d.Log.WarnContext(ctx, "Refused auth probe of a non-public URL", "instance_id", inst.ID, "error", err)
		return ProbeResult{}, &domain.Invalid{Msg: "The configured endpoint is not an allowed address"}
	}
	if _, err := s.discoverAuthServer(ctx, mcpURL); err == nil {
		return ProbeResult{Status: "auth_required", Methods: []string{"oauth", "credentials"}}, nil
	}
	status, err := s.getStatus(ctx, mcpURL, true)
	if err != nil {
		var ne net.Error
		switch {
		case errors.Is(err, netguard.ErrUnsafe):
			return ProbeResult{}, &domain.Invalid{Msg: "The configured endpoint is not an allowed address"}
		case errors.As(err, &ne) && ne.Timeout():
			return ProbeResult{}, &domain.Invalid{Msg: "Connection to " + mcpURL + " timed out"}
		case mcpclient.IsTransient(err):
			return ProbeResult{}, &domain.Invalid{Msg: "Cannot connect to the configured endpoint"}
		}
		s.d.Log.WarnContext(ctx, "Probe failed", "instance_id", inst.ID, "error", err)
		return ProbeResult{}, &domain.Invalid{Msg: "Probe failed due to an internal error"}
	}
	switch status {
	case http.StatusOK, http.StatusMethodNotAllowed:
		return ProbeResult{Status: "ok", Methods: []string{"none"}}, nil
	case http.StatusUnauthorized, http.StatusForbidden:
		// Some servers (Vercel) answer an unauthenticated request with 403.
		hints := []any{}
		if found {
			hints = credentialHints(spec.EnvSchema)
		}
		return ProbeResult{Status: "auth_required", Methods: []string{"credentials"}, Hints: hints, HasHints: true}, nil
	}
	return ProbeResult{}, &domain.Invalid{Msg: "Unexpected response: " + strconv.Itoa(status)}
}

// credentialHints are the env_schema entries that look like a credential.
func credentialHints(schema []any) []any {
	hints := []any{}
	for _, e := range schema {
		m, ok := e.(map[string]any)
		if !ok {
			continue
		}
		name, _ := m["name"].(string)
		switch strings.ToUpper(name) {
		case "AUTHORIZATION", "API_KEY", "TOKEN":
		default:
			continue
		}
		desc, ok := m["description"]
		if !ok {
			desc = ""
		}
		req, ok := m["required"]
		if !ok {
			req = true
		}
		hints = append(hints, map[string]any{"name": name, "description": desc, "required": req})
	}
	return hints
}

func orEmpty(l []string) []string {
	if l == nil {
		return []string{}
	}
	return l
}
