package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mcpserve"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpserver"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// proxyDropsResponseHeader is a response header a proxy never relays: the
// hop-by-hop ones (RFC 7230 §6.1), the ones the server recomputes, and cookies.
func proxyDropsResponseHeader(name string) bool {
	switch strings.ToLower(name) {
	case "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
		"transfer-encoding", "upgrade", "host", "content-length", "set-cookie":
		return true
	}
	return false
}

// proxyForwardsRequestHeader is a caller's header the upstream receives:
// every Mcp-* one and the content negotiation, nothing else (cookies, its auth).
func proxyForwardsRequestHeader(name string) bool {
	switch n := strings.ToLower(name); n {
	case "accept", "content-type", "last-event-id":
		return true
	default:
		return strings.HasPrefix(n, "mcp-")
	}
}

const proxyMaxBody = 16 << 20

// mountProxy routes the per-instance reverse proxy (v1/mcp_proxy.py).
func mountProxy(g group) {
	if g.e.Gate == nil || g.e.Authenticate == nil || !g.s.svc.ProxyReady() {
		return
	}
	p := &instanceProxy{g: g}
	r := g.r.With(g.e.Authenticate)
	for _, method := range []string{http.MethodGet, http.MethodPost, http.MethodDelete} {
		r.Method(method, "/v1/mcp/{instance_id}/mcp", p)
	}
}

type instanceProxy struct{ g group }

func (p *instanceProxy) fail(w http.ResponseWriter, r *http.Request, status int, detail string) {
	p.g.errs.Write(w, r, httpx.HTTPError(status, detail))
}

func (p *instanceProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	svc := p.g.s.svc
	prin, ok := authn.PrincipalFrom(ctx)
	if !ok {
		p.g.errs.Write(w, r, authn.ErrNoPrincipal)
		return
	}
	id, wsID, err := svc.LocateConnection(ctx, prin, chi.URLParam(r, "instance_id"))
	if err != nil {
		p.g.errs.Write(w, r, err)
		return
	}
	c, err := p.g.e.Gate.EnterWorkspace(ctx, prin, wsID)
	if err != nil {
		var unreachable *scope.UnreachableError
		if errors.As(err, &unreachable) {
			p.fail(w, r, http.StatusNotFound, "MCP instance not found")
			return
		}
		p.g.errs.Write(w, r, err)
		return
	}
	ctx = authn.WithCaller(ctx, c)
	r = r.WithContext(ctx)
	if err := svc.Require(ctx, c, "use_connection", "mcp_instance", id.String()); err != nil {
		p.g.errs.Write(w, r, err)
		return
	}
	inst, isOpenAPI, err := svc.ProxyTarget(ctx, c, id)
	if err != nil {
		p.g.errs.Write(w, r, err)
		return
	}
	if isOpenAPI {
		p.connection(c, id).ServeHTTP(w, r)
		return
	}
	var body []byte
	if r.Method == http.MethodPost || r.Method == http.MethodDelete {
		body, err = io.ReadAll(io.LimitReader(r.Body, proxyMaxBody+1))
		if err != nil || len(body) > proxyMaxBody {
			p.fail(w, r, http.StatusBadRequest, "Request body could not be read")
			return
		}
	}
	up, err := svc.UpstreamFor(ctx, c.Workspace, inst, &service.CallerContext{
		UserID: c.UserID, UserEmail: c.Email, ClientID: c.ClientID, Tool: service.SingleToolCall(body),
	})
	if err != nil {
		var authErr *service.UpstreamAuthError
		if errors.As(err, &authErr) {
			p.g.s.svc.Log().ErrorContext(ctx, "Failed to build outbound auth headers for instance", "instance_id", inst.ID, "error", authErr.Err)
			p.fail(w, r, http.StatusBadGateway, "Upstream auth failed")
			return
		}
		p.g.errs.Write(w, r, err)
		return
	}
	if r.Method == http.MethodPost {
		if err := svc.JudgeProxyRequest(ctx, c, inst.ID, body, r.Header); err != nil {
			var refusal *service.ProxyRefusal
			if errors.As(err, &refusal) && refusal.Body != nil {
				proxyWriteJSON(w, refusal.Status, refusal.Body)
				return
			}
			if errors.As(err, &refusal) {
				p.fail(w, r, refusal.Status, refusal.Detail)
				return
			}
			p.g.errs.Write(w, r, err)
			return
		}
	}
	resp, err := proxySend(ctx, r, up, body)
	if err != nil {
		p.g.s.svc.Log().WarnContext(ctx, "Upstream MCP error", "instance_id", inst.ID, "error", err)
		p.fail(w, r, http.StatusBadGateway, "Upstream MCP error: "+err.Error())
		return
	}
	defer func() { _ = resp.Body.Close() }()
	proxyRelay(w, resp)
}

// proxyRelay writes the upstream response back without its hop-by-hop
// headers and cookies.
func proxyRelay(w http.ResponseWriter, resp *http.Response) {
	for k, vs := range resp.Header {
		if proxyDropsResponseHeader(k) {
			continue
		}
		for _, v := range vs {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(resp.StatusCode)
	proxyStream(w, resp.Body)
}

// proxySend forwards r to the upstream with only the caller's MCP headers
// and the instance's own outbound ones.
func proxySend(ctx context.Context, r *http.Request, up service.Upstream, body []byte) (*http.Response, error) {
	target := up.URL
	if r.URL.RawQuery != "" {
		sep := "?"
		if strings.Contains(target, "?") {
			sep = "&"
		}
		target += sep + r.URL.RawQuery
	}
	var rd io.Reader
	if body != nil {
		rd = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, r.Method, target, rd)
	if err != nil {
		return nil, err
	}
	for k, vs := range r.Header {
		if !proxyForwardsRequestHeader(k) {
			continue
		}
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}
	for k, vs := range up.Headers {
		req.Header[http.CanonicalHeaderKey(k)] = vs
	}
	return up.Transport.RoundTrip(req)
}

// stream relays the upstream body as it arrives, flushing each chunk so an
// event stream reaches the caller unbuffered.
func proxyStream(w http.ResponseWriter, body io.Reader) {
	rc := http.NewResponseController(w)
	buf := make([]byte, 32<<10)
	for {
		n, err := body.Read(buf)
		if n > 0 {
			if _, werr := w.Write(buf[:n]); werr != nil {
				return
			}
			_ = rc.Flush()
		}
		if err != nil {
			return
		}
	}
}

func proxyWriteJSON(w http.ResponseWriter, status int, v any) {
	raw, err := json.Marshal(v)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(raw)
}

// connection serves an API connection as an MCP server (connection_mcp.py),
// as the caller the proxy already admitted.
func (p *instanceProxy) connection(c authn.Caller, id uuid.UUID) http.Handler {
	svc := p.g.s.svc
	return &mcpserver.Endpoint{
		Info: mcpserver.Identity(svc.APIURL(), "AgentArea API connection", "The operations of one API connection, as tools."),
		Log:  svc.Log(),
		Backend: func(*http.Request) (mcpserver.Backend, error) {
			return proxyConnectionBackend{svc: svc, c: c, id: id.String()}, nil
		},
	}
}

type proxyConnectionBackend struct {
	svc *service.Service
	c   authn.Caller
	id  string
}

func (b proxyConnectionBackend) ListTools(ctx context.Context) ([]mcpserver.Tool, error) {
	ops, err := b.svc.ConnectionTools(ctx, b.c, b.id)
	if err != nil {
		return nil, err
	}
	out := make([]mcpserver.Tool, 0, len(ops))
	for _, op := range ops {
		schema, err := json.Marshal(op.InputSchema)
		if err != nil {
			return nil, err
		}
		out = append(out, mcpserver.Tool{Tool: mcpserve.Tool{Name: op.Name, Description: op.Description, InputSchema: schema}})
	}
	return out, nil
}

func (b proxyConnectionBackend) CallTool(ctx context.Context, name string, args json.RawMessage) (any, error) {
	res, err := b.svc.CallConnectionTool(ctx, b.c, b.id, name, args)
	if err != nil {
		return nil, err
	}
	return mcpserve.Result{Content: []mcpserve.Content{{Type: "text", Text: res.Text}}, IsError: res.IsError, StructuredContent: res.StructuredContent}, nil
}
