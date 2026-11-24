// Package mcpclient is the MCP client every outbound MCP call of connections
// uses (agentarea_mcp/application/mcp_client.py over the MCP SDK): streamable
// HTTP with the SSE transport as fallback, era negotiation (the 2026-07-28
// server/discover envelope or the initialize handshake) with a verdict cache,
// tools/list, tools/call with progress, over a caller-supplied RoundTripper.
package mcpclient

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

// Protocol versions this client speaks.
const (
	ModernVersion    = "2026-07-28"
	HandshakeVersion = "2025-11-25"
)

func handshakeVersions() []string {
	return []string{"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
}

func modernVersions() []string { return []string{ModernVersion} }

// Wire keys of the modern per-request envelope.
const (
	metaProtocolVersion = "io.modelcontextprotocol/protocolVersion"
	metaClientInfo      = "io.modelcontextprotocol/clientInfo()"
	metaCapabilities    = "io.modelcontextprotocol/clientCapabilities"
	headerVersion       = "Mcp-Protocol-Version"
	headerMethod        = "Mcp-Method"
	headerName          = "Mcp-Name"
)

// Timeouts the Python client used.
const (
	DefaultReadTimeout = 300 * time.Second
	discoverTimeout    = 10 * time.Second
	maxListPages       = 100
)

func clientInfo() map[string]any { return map[string]any{"name": "agentarea", "version": "1.0.0"} }

// Options is one connection's target.
type Options struct {
	URL string
	// Transport is the declared remote transport (streamable-http or sse);
	// empty probes by URL suffix.
	Transport string
	// RoundTripper dials: the pinned transport for a member's URL, the
	// gateway adapter for a workload.
	RoundTripper http.RoundTripper
	Headers      http.Header
	// ReadTimeout is how long a response may stay silent; 0 is 300 s.
	ReadTimeout time.Duration
	// Verdicts caches the negotiated era under VerdictKey; nil negotiates every time.
	Verdicts   *Verdicts
	VerdictKey string
}

// Candidates is mcp_transport_candidates: the streamable HTTP URLs to try
// in order, and the SSE fallback ("" for none).
func Candidates(endpoint, transport string) ([]string, string) {
	u := strings.TrimRight(endpoint, "/")
	switch strings.ReplaceAll(strings.ToLower(transport), "_", "-") {
	case "streamable-http":
		return []string{u}, ""
	case "sse":
		return nil, u
	}
	switch {
	case strings.HasSuffix(u, "/sse"):
		return nil, u
	case strings.HasSuffix(u, "/mcp"):
		return []string{u}, strings.TrimSuffix(u, "/mcp") + "/sse"
	}
	return []string{u, u + "/mcp"}, u + "/sse"
}

// VerdictKey is mcp_verdict_key: the instance and a fingerprint of the
// runtime identity it connects with.
func VerdictKey(instanceID string, spec map[string]any) string {
	raw, err := json.Marshal(spec)
	if err != nil {
		raw = []byte(fmt.Sprint(spec))
	}
	sum := sha256.Sum256(raw)
	return instanceID + ":" + hex.EncodeToString(sum[:])
}

// Verdicts is the era verdict cache (the Redis mcp:era:* keys, in process).
type Verdicts struct {
	mu  sync.Mutex
	m   map[string]verdict
	ttl time.Duration
	now func() time.Time
}

type verdict struct {
	legacy   bool
	discover json.RawMessage
	at       time.Time
}

// NewVerdicts keeps verdicts for ttl (24 h in Python).
func NewVerdicts(ttl time.Duration) *Verdicts {
	return &Verdicts{m: map[string]verdict{}, ttl: ttl, now: time.Now}
}

func (v *Verdicts) get(key string) (verdict, bool) {
	if v == nil || key == "" {
		return verdict{}, false
	}
	v.mu.Lock()
	defer v.mu.Unlock()
	got, ok := v.m[key]
	if ok && v.now().Sub(got.at) > v.ttl {
		delete(v.m, key)
		return verdict{}, false
	}
	return got, ok
}

func (v *Verdicts) set(key string, got verdict) {
	if v == nil || key == "" {
		return
	}
	v.mu.Lock()
	defer v.mu.Unlock()
	got.at = v.now()
	v.m[key] = got
}

func (v *Verdicts) forget(key string) {
	if v == nil || key == "" {
		return
	}
	v.mu.Lock()
	defer v.mu.Unlock()
	delete(v.m, key)
}

// Client is a connected MCP client.
type Client struct {
	o      Options
	open   func(ctx context.Context) (wire, error)
	nextID atomic.Int64

	w            wire
	version      string
	modern       bool
	capabilities map[string]any
	discover     json.RawMessage

	cached  bool
	retried bool
}

// Connect opens a client: the streamable candidates in order, then SSE. A
// refusal (401/403) on any candidate is the error when none connects.
func Connect(ctx context.Context, o Options) (*Client, error) {
	if o.ReadTimeout <= 0 {
		o.ReadTimeout = DefaultReadTimeout
	}
	x := newExchange(o.RoundTripper, o.Headers, o.ReadTimeout)
	streamURLs, sseURL := Candidates(o.URL, o.Transport)
	var lastErr error
	var refused *UnauthorizedError
	try := func(open func(ctx context.Context) (wire, error)) (*Client, bool) {
		c := &Client{o: o, open: open}
		if err := c.start(ctx); err != nil {
			lastErr = err
			var un *UnauthorizedError
			if errors.As(err, &un) {
				refused = un
			}
			return nil, false
		}
		return c, true
	}
	for _, u := range streamURLs {
		if ctx.Err() != nil {
			break
		}
		if c, ok := try(func(context.Context) (wire, error) {
			return &streamable{exchange: x, url: u}, nil
		}); ok {
			return c, nil
		}
	}
	if sseURL != "" && ctx.Err() == nil {
		if c, ok := try(func(ctx context.Context) (wire, error) {
			return openLegacySSE(ctx, x, sseURL)
		}); ok {
			return c, nil
		}
	}
	if refused != nil {
		return nil, refused
	}
	if lastErr == nil {
		lastErr = ctx.Err()
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("no usable MCP transport for %s", netguard.SafeURL(o.URL))
	}
	return nil, lastErr
}

// start negotiates on a fresh wire, from the cached verdict when there is one.
func (c *Client) start(ctx context.Context) error {
	got, cached := c.o.Verdicts.get(c.o.VerdictKey)
	if c.retried {
		cached = false
	}
	c.cached = cached
	w, err := c.open(ctx)
	if err != nil {
		return err
	}
	c.w = w
	switch {
	case cached && got.legacy:
		err = c.initialize(ctx)
	case cached:
		err = c.adopt(got.discover)
	default:
		err = c.negotiate(ctx)
	}
	if err != nil {
		c.w.close()
		c.w = nil
		return err
	}
	if !cached {
		if c.modern {
			c.o.Verdicts.set(c.o.VerdictKey, verdict{discover: c.discover})
		} else {
			c.o.Verdicts.set(c.o.VerdictKey, verdict{legacy: true})
		}
	}
	return nil
}

// Close ends the session.
func (c *Client) Close() {
	if c.w != nil {
		c.w.close()
		c.w = nil
	}
}

// ProtocolVersion is the negotiated version.
func (c *Client) ProtocolVersion() string { return c.version }

// ServerCapabilities is what the server declared.
func (c *Client) ServerCapabilities() map[string]any { return c.capabilities }

func (c *Client) negotiate(ctx context.Context) error {
	version := ModernVersion
	for attempt := range 2 {
		raw, err := c.discoverAt(ctx, version)
		if err != nil {
			var rpc *RPCError
			if !errors.As(err, &rpc) {
				return err
			}
			if rpc.Code == CodeUnsupportedVersion {
				supported, listed := supportedOf(rpc.Data)
				mutual := intersect(modernVersions(), supported)
				if len(mutual) > 0 && attempt == 0 {
					version = mutual[len(mutual)-1]
					continue
				}
				if listed && len(intersect(handshakeVersions(), supported)) == 0 {
					return err
				}
			}
			if herr := c.initialize(ctx); herr != nil {
				var hr *RPCError
				if !errors.As(herr, &hr) || hr.Code != CodeUnsupportedVersion || attempt != 0 {
					return herr
				}
				supported, _ := supportedOf(hr.Data)
				mutual := intersect(modernVersions(), supported)
				if len(mutual) == 0 {
					return herr
				}
				version = mutual[len(mutual)-1]
				continue
			}
			return nil
		}
		var res struct {
			SupportedVersions []string       `json:"supportedVersions"`
			Capabilities      map[string]any `json:"capabilities"`
		}
		if json.Unmarshal(raw, &res) != nil || res.Capabilities == nil ||
			len(intersect(modernVersions(), res.SupportedVersions)) == 0 {
			return c.initialize(ctx)
		}
		return c.adopt(raw)
	}
	return errors.New("era negotiation did not settle")
}

func supportedOf(data any) ([]string, bool) {
	m, ok := data.(map[string]any)
	if !ok {
		return nil, false
	}
	l, ok := m["supported"].([]any)
	if !ok {
		return nil, false
	}
	out := make([]string, 0, len(l))
	for _, v := range l {
		s, ok := v.(string)
		if !ok {
			return nil, false
		}
		out = append(out, s)
	}
	return out, true
}

func intersect(ordered, have []string) []string {
	var out []string
	for _, v := range ordered {
		if slices.Contains(have, v) {
			out = append(out, v)
		}
	}
	return out
}

func (c *Client) id() *int64 {
	n := c.nextID.Add(1)
	return &n
}

func modernMeta(version string) map[string]any {
	return map[string]any{
		metaProtocolVersion: version,
		metaClientInfo:      clientInfo(),
		metaCapabilities:    map[string]any{},
	}
}

func (c *Client) discoverAt(ctx context.Context, version string) (json.RawMessage, error) {
	ctx, cancel := context.WithTimeout(ctx, discoverTimeout)
	defer cancel()
	req := outbound{JSONRPC: "2.0", ID: c.id(), Method: "server/discover",
		Params: map[string]any{"_meta": modernMeta(version)}}
	h := http.Header{headerVersion: {version}, headerMethod: {req.Method}}
	m, err := c.w.roundTrip(ctx, req, h, nil)
	if err != nil {
		return nil, err
	}
	if m.Error != nil {
		return nil, m.Error
	}
	return m.Result, nil
}

func (c *Client) adopt(raw json.RawMessage) error {
	var res struct {
		SupportedVersions []string       `json:"supportedVersions"`
		Capabilities      map[string]any `json:"capabilities"`
	}
	if err := json.Unmarshal(raw, &res); err != nil {
		return err
	}
	mutual := intersect(modernVersions(), res.SupportedVersions)
	if len(mutual) == 0 {
		return fmt.Errorf("no mutually supported modern protocol version (server: %v)", res.SupportedVersions)
	}
	c.version, c.modern, c.capabilities, c.discover = mutual[len(mutual)-1], true, res.Capabilities, raw
	return nil
}

func (c *Client) initialize(ctx context.Context) error {
	req := outbound{JSONRPC: "2.0", ID: c.id(), Method: "initialize", Params: map[string]any{
		"protocolVersion": HandshakeVersion,
		"capabilities":    map[string]any{},
		"clientInfo()":    clientInfo(),
	}}
	m, err := c.w.roundTrip(ctx, req, nil, nil)
	if err != nil {
		return err
	}
	if m.Error != nil {
		return m.Error
	}
	var res struct {
		ProtocolVersion string         `json:"protocolVersion"`
		Capabilities    map[string]any `json:"capabilities"`
	}
	if err := json.Unmarshal(m.Result, &res); err != nil {
		return &RPCError{Code: CodeParseError, Message: "invalid initialize result: " + err.Error()}
	}
	if !slices.Contains(handshakeVersions(), res.ProtocolVersion) {
		return fmt.Errorf("unsupported protocol version from the server: %s", res.ProtocolVersion)
	}
	c.version, c.modern, c.capabilities, c.discover = res.ProtocolVersion, false, res.Capabilities, nil
	if c.capabilities == nil {
		c.capabilities = map[string]any{}
	}
	return c.w.send(ctx, outbound{JSONRPC: "2.0", Method: "notifications/initialized"},
		http.Header{headerVersion: {c.version}})
}

// Progress is one notifications/progress of a call.
type Progress struct {
	Progress float64
	Total    *float64
	Message  string
}

// call sends one request on the negotiated session.
func (c *Client) call(ctx context.Context, method string, params map[string]any, extra http.Header, progress func(Progress)) (json.RawMessage, error) {
	if c.w == nil {
		return nil, errors.New("MCP client is not connected")
	}
	if params == nil {
		params = map[string]any{}
	}
	id := c.id()
	if progress != nil {
		meta, _ := params["_meta"].(map[string]any)
		meta = cloneMap(meta)
		meta["progressToken"] = *id
		params["_meta"] = meta
	}
	h := http.Header{headerVersion: {c.version}}
	if c.modern {
		meta, _ := params["_meta"].(map[string]any)
		meta = cloneMap(meta)
		for k, v := range modernMeta(c.version) {
			meta[k] = v
		}
		params["_meta"] = meta
		h.Set(headerMethod, method)
		key := map[string]string{"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}[method]
		if name, ok := params[key].(string); key != "" && ok {
			h.Set(headerName, EncodeHeaderValue(name))
		}
	}
	for k, vs := range extra {
		h[k] = vs
	}
	req := outbound{JSONRPC: "2.0", ID: id, Method: method, Params: params}
	notes := func(m inbound) {
		if m.ID != nil && m.Method != "" {
			c.answer(ctx, m, h)
			return
		}
		if m.Method != "notifications/progress" || progress == nil {
			return
		}
		var p struct {
			ProgressToken json.Number `json:"progressToken"`
			Progress      float64     `json:"progress"`
			Total         *float64    `json:"total"`
			Message       string      `json:"message"`
		}
		if json.Unmarshal(m.Params, &p) == nil && p.ProgressToken.String() == fmt.Sprint(*id) {
			progress(Progress{Progress: p.Progress, Total: p.Total, Message: p.Message})
		}
	}
	m, err := c.w.roundTrip(ctx, req, h, notes)
	if err != nil {
		if ctx.Err() != nil && !c.modern {
			c.cancelled(*id, h)
		}
		return nil, err
	}
	if m.Error != nil {
		return nil, m.Error
	}
	return m.Result, nil
}

// answer replies to a request the server sent mid-call: ping, nothing else.
func (c *Client) answer(ctx context.Context, m inbound, h http.Header) {
	resp := outbound{JSONRPC: "2.0"}
	if err := json.Unmarshal(m.ID, new(json.RawMessage)); err != nil {
		return
	}
	var id int64
	if json.Unmarshal(m.ID, &id) != nil {
		return
	}
	resp.ID = &id
	if m.Method == "ping" {
		resp.Result = json.RawMessage(`{}`)
	} else {
		resp.Error = &RPCError{Code: CodeMethodNotFound, Message: "Method not found"}
	}
	go func() {
		sctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
		defer cancel()
		_ = c.w.send(sctx, resp, h)
	}()
}

// cancelled tells a handshake-era server a call was abandoned.
func (c *Client) cancelled(id int64, h http.Header) {
	w := c.w
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = w.send(ctx, outbound{JSONRPC: "2.0", Method: "notifications/cancelled",
			Params: map[string]any{"requestId": id, "reason": "timed out"}}, h)
	}()
}

func cloneMap(m map[string]any) map[string]any {
	out := make(map[string]any, len(m)+4)
	for k, v := range m {
		out[k] = v
	}
	return out
}

// EncodeHeaderValue wraps a value that would not survive an HTTP field in
// the =?base64?...?= sentinel (encode_header_value).
func EncodeHeaderValue(v string) string {
	safe := v == strings.TrimSpace(v) && (!strings.HasPrefix(v, "=?base64?") || !strings.HasSuffix(v, "?="))
	for _, r := range v {
		if r < 0x20 || r > 0x7e {
			safe = false
			break
		}
	}
	if safe {
		return v
	}
	return "=?base64?" + base64.StdEncoding.EncodeToString([]byte(v)) + "?="
}

// invoke runs op; a negotiation error on a connection opened from a cached
// verdict drops the verdict and runs op once more on a fresh negotiation.
func (c *Client) invoke(ctx context.Context, op func() (json.RawMessage, error)) (json.RawMessage, error) {
	raw, err := op()
	if err == nil || !c.ForgetStaleVerdict(err) {
		return raw, err
	}
	c.Close()
	if err := c.start(ctx); err != nil {
		return nil, err
	}
	return op()
}

// ForgetStaleVerdict drops a cached era verdict the server just contradicted,
// once: true when err is a negotiation error on a cached connection.
func (c *Client) ForgetStaleVerdict(err error) bool {
	var rpc *RPCError
	if !errors.As(err, &rpc) || !c.cached || c.retried ||
		(rpc.Code != CodeUnsupportedVersion && rpc.Code != CodeMethodNotFound) {
		return false
	}
	c.o.Verdicts.forget(c.o.VerdictKey)
	c.retried, c.cached = true, false
	return true
}

// Request sends any request (events/list) and returns its raw result.
func (c *Client) Request(ctx context.Context, method string, params map[string]any) (json.RawMessage, error) {
	return c.invoke(ctx, func() (json.RawMessage, error) { return c.call(ctx, method, cloneMap(params), nil, nil) })
}

// ListTools is every tool, page by page; each as the server sent it.
func (c *Client) ListTools(ctx context.Context) ([]map[string]any, error) {
	var tools []map[string]any
	cursor := ""
	seen := map[string]bool{}
	for range maxListPages {
		params := map[string]any{}
		if cursor != "" {
			params["cursor"] = cursor
		}
		raw, err := c.invoke(ctx, func() (json.RawMessage, error) { return c.call(ctx, "tools/list", params, nil, nil) })
		if err != nil {
			return nil, err
		}
		var page struct {
			Tools      []map[string]any `json:"tools"`
			NextCursor string           `json:"nextCursor"`
		}
		if err := decodeNumbers(raw, &page); err != nil {
			return nil, &RPCError{Code: CodeParseError, Message: "invalid tools/list result: " + err.Error()}
		}
		tools = append(tools, page.Tools...)
		if page.NextCursor == "" {
			return tools, nil
		}
		if seen[page.NextCursor] {
			return nil, fmt.Errorf("tools/list cursor %q repeats", page.NextCursor)
		}
		seen[page.NextCursor] = true
		cursor = page.NextCursor
	}
	return nil, fmt.Errorf("tools/list has more than %d pages", maxListPages)
}

// Call is one tools/call.
type Call struct {
	Name      string
	Arguments map[string]any
	// Meta is merged into params._meta.
	Meta map[string]any
	// Headers go on this call's requests only (the signed context).
	Headers http.Header
	// Timeout bounds the call, progress included; 0 is none.
	Timeout  time.Duration
	Progress func(Progress)
}

// CallResult is a tools/call result.
type CallResult struct {
	Content           []map[string]any `json:"content"`
	StructuredContent any              `json:"structuredContent"`
	IsError           bool             `json:"isError"`
	Meta              map[string]any   `json:"_meta"`
}

// CallTool runs the tool; a call past Timeout fails with a REQUEST_TIMEOUT RPCError.
func (c *Client) CallTool(ctx context.Context, call Call) (*CallResult, error) {
	return c.callTool(ctx, call, true)
}

// CallToolOnce is CallTool without the stale-verdict retry.
func (c *Client) CallToolOnce(ctx context.Context, call Call) (*CallResult, error) {
	return c.callTool(ctx, call, false)
}

func (c *Client) callTool(ctx context.Context, call Call, retry bool) (*CallResult, error) {
	args := call.Arguments
	if args == nil {
		args = map[string]any{}
	}
	op := func() (json.RawMessage, error) {
		cctx, cancel := ctx, context.CancelFunc(func() {})
		if call.Timeout > 0 {
			cctx, cancel = context.WithTimeout(ctx, call.Timeout)
		}
		defer cancel()
		params := map[string]any{"name": call.Name, "arguments": args}
		if len(call.Meta) > 0 {
			params["_meta"] = cloneMap(call.Meta)
		}
		raw, err := c.call(cctx, "tools/call", params, call.Headers, call.Progress)
		if err != nil && ctx.Err() == nil && cctx.Err() != nil {
			return nil, &RPCError{Code: CodeRequestTimeout, Message: fmt.Sprintf(
				"Timed out while waiting for response to tools/call. Waited %s.", call.Timeout)}
		}
		return raw, err
	}
	var raw json.RawMessage
	var err error
	if retry {
		raw, err = c.invoke(ctx, op)
	} else {
		raw, err = op()
	}
	if err != nil {
		return nil, err
	}
	var res CallResult
	if err := decodeNumbers(raw, &res); err != nil {
		return nil, &RPCError{Code: CodeParseError, Message: "invalid tools/call result: " + err.Error()}
	}
	return &res, nil
}
