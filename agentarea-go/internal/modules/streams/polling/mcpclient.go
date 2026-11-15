package polling

// The client side of MCP Events (SEP-3415, draft PR #3415 at 2ec39b9c, protocol
// 2026-07-28) to a member's MCP instance through the mcp-manager gateway, which
// adds the instance's credentials: the pollers never hold them. Requests are
// stateless JSON-RPC over Streamable HTTP; an answer is JSON or an SSE stream.

import (
	"bufio"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"
	"sync/atomic"
	"time"
)

// MCPProtocolVersion is the MCP revision the events extension is defined for.
const MCPProtocolVersion = "2026-07-28"

// MCPEventsExtension is the events extension identifier.
const MCPEventsExtension = "io.modelcontextprotocol/events"

// CodeNotFound is the extension's error for an unknown event or subscription.
const CodeNotFound = -32023

const (
	gatewayAuthHeader = "X-AgentArea-Manager-Authorization"
	maxAnswerBytes    = 8 << 20
	mcpCallTimeout    = 60 * time.Second
)

// RPCError is a JSON-RPC error the MCP server answered with.
type RPCError struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data,omitempty"`
}

func (e *RPCError) Error() string {
	if len(e.Data) > 0 {
		return fmt.Sprintf("MCP error %d %s: %s", e.Code, e.Message, excerpt(e.Data))
	}
	return fmt.Sprintf("MCP error %d %s", e.Code, e.Message)
}

// MCPPollRequest is one events/poll.
type MCPPollRequest struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
	// Cursor nil asks to start from now.
	Cursor    *string `json:"cursor"`
	MaxEvents int     `json:"maxEvents,omitempty"`
}

// MCPPollResult is what events/poll answered.
type MCPPollResult struct {
	Events     []json.RawMessage `json:"events"`
	Cursor     *string           `json:"cursor"`
	Truncated  bool              `json:"truncated"`
	HasMore    bool              `json:"hasMore"`
	NextPollMs int64             `json:"nextPollMs"`
}

// Delivery is where a webhook subscription posts.
type Delivery struct {
	Mode   string `json:"mode,omitempty"`
	URL    string `json:"url"`
	Secret string `json:"secret,omitempty"`
}

// SubscribeRequest is one events/subscribe (also its refresh).
type SubscribeRequest struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
	Delivery  Delivery       `json:"delivery"`
	Cursor    *string        `json:"cursor"`
	TTLMs     int64          `json:"ttlMs"`
}

// SubscribeResult is the server's grant.
type SubscribeResult struct {
	ID string `json:"id"`
	// RefreshBefore nil is a grant with no expiry.
	RefreshBefore *time.Time `json:"refreshBefore"`
	Cursor        *string    `json:"cursor"`
	Truncated     bool       `json:"truncated"`
}

// UnsubscribeRequest names the subscription by its key: name, arguments, url.
type UnsubscribeRequest struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
	Delivery  Delivery       `json:"delivery"`
}

// MCPClient calls instances through the gateway at base.
type MCPClient struct {
	base   string
	secret string
	http   *http.Client
	ids    atomic.Int64
}

// NewMCPClient builds a client for the gateway at base (the manager's URL), authorized by
// the gateway secret; rt is the deployment's transport to its own services.
func NewMCPClient(base, secret string, rt http.RoundTripper) *MCPClient {
	return &MCPClient{
		base:   strings.TrimRight(base, "/"),
		secret: secret,
		http: &http.Client{
			Transport: rt,
			Timeout:   mcpCallTimeout,
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
}

// Poll calls events/poll.
func (c *MCPClient) Poll(ctx context.Context, instanceID string, req MCPPollRequest) (MCPPollResult, error) {
	var out MCPPollResult
	err := c.call(ctx, instanceID, "events/poll", req.Name, req, &out)
	return out, err
}

// Subscribe calls events/subscribe, which creates or refreshes the subscription.
func (c *MCPClient) Subscribe(ctx context.Context, instanceID string, req SubscribeRequest) (SubscribeResult, error) {
	req.Delivery.Mode = "webhook"
	var out SubscribeResult
	if err := c.call(ctx, instanceID, "events/subscribe", req.Name, req, &out); err != nil {
		return SubscribeResult{}, err
	}
	if out.ID == "" {
		return SubscribeResult{}, errors.New("events/subscribe answered no subscription id")
	}
	return out, nil
}

// Unsubscribe calls events/unsubscribe.
func (c *MCPClient) Unsubscribe(ctx context.Context, instanceID string, req UnsubscribeRequest) error {
	req.Delivery = Delivery{URL: req.Delivery.URL}
	return c.call(ctx, instanceID, "events/unsubscribe", req.Name, req, nil)
}

type envelope struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *RPCError       `json:"error,omitempty"`
}

func (c *MCPClient) call(ctx context.Context, instanceID, method, name string, params, out any) error {
	body, id, err := c.request(method, params)
	if err != nil {
		return err
	}
	endpoint := c.base + "/mcp/" + url.PathEscape(instanceID) + "/mcp"
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("%s: %w", method, err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "application/json, text/event-stream")
	httpReq.Header.Set("MCP-Protocol-Version", MCPProtocolVersion)
	httpReq.Header.Set("Mcp-Method", method)
	if name != "" {
		httpReq.Header.Set("Mcp-Name", EncodeHeaderValue(name))
	}
	httpReq.Header.Set(gatewayAuthHeader, "Bearer "+c.secret)

	resp, err := c.http.Do(httpReq)
	if err != nil {
		var urlErr *url.Error
		if errors.As(err, &urlErr) {
			err = urlErr.Err
		}
		return fmt.Errorf("%s through the MCP gateway: %w", method, err)
	}
	defer func() { _ = resp.Body.Close() }()
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxAnswerBytes+1))
	if err != nil {
		return fmt.Errorf("%s: read answer: %w", method, err)
	}
	if len(data) > maxAnswerBytes {
		return fmt.Errorf("%s: answer is over %d bytes", method, maxAnswerBytes)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		var answer envelope
		if json.Unmarshal(data, &answer) == nil && answer.Error != nil {
			return answer.Error
		}
		return fmt.Errorf("%s: HTTP %d: %s", method, resp.StatusCode, excerpt(data))
	}
	answer, err := readAnswer(resp.Header.Get("Content-Type"), data, id)
	if err != nil {
		return fmt.Errorf("%s: %w", method, err)
	}
	if answer.Error != nil {
		return answer.Error
	}
	if out == nil {
		return nil
	}
	if err := json.Unmarshal(answer.Result, out); err != nil {
		return fmt.Errorf("%s: result: %w", method, err)
	}
	return nil
}

func (c *MCPClient) request(method string, params any) ([]byte, json.RawMessage, error) {
	encoded, err := json.Marshal(params)
	if err != nil {
		return nil, nil, fmt.Errorf("%s params: %w", method, err)
	}
	var fields map[string]any
	if err := json.Unmarshal(encoded, &fields); err != nil {
		return nil, nil, fmt.Errorf("%s params: %w", method, err)
	}
	fields["_meta"] = map[string]any{
		"io.modelcontextprotocol/protocolVersion": MCPProtocolVersion,
		"io.modelcontextprotocol/clientInfo":      map[string]any{"name": "agentarea-events", "version": "1"},
		"io.modelcontextprotocol/clientCapabilities": map[string]any{
			"extensions": map[string]any{MCPEventsExtension: map[string]any{}},
		},
	}
	n := c.ids.Add(1)
	body, err := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": n, "method": method, "params": fields})
	return body, json.RawMessage(fmt.Sprintf("%d", n)), err
}

// readAnswer takes the JSON-RPC answer to id from a JSON body or an SSE stream.
func readAnswer(contentType string, data []byte, id json.RawMessage) (envelope, error) {
	mediaType, _, _ := mime.ParseMediaType(contentType)
	if mediaType != "text/event-stream" {
		var answer envelope
		if err := json.Unmarshal(data, &answer); err != nil {
			return envelope{}, fmt.Errorf("answer is not JSON-RPC: %w", err)
		}
		return answer, nil
	}
	scanner := bufio.NewScanner(bytes.NewReader(data))
	scanner.Buffer(make([]byte, 0, 64<<10), maxAnswerBytes)
	var event strings.Builder
	flush := func() (envelope, bool) {
		defer event.Reset()
		if event.Len() == 0 {
			return envelope{}, false
		}
		var answer envelope
		if json.Unmarshal([]byte(event.String()), &answer) != nil || !bytes.Equal(answer.ID, id) {
			return envelope{}, false
		}
		return answer, answer.Result != nil || answer.Error != nil
	}
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			if answer, ok := flush(); ok {
				return answer, nil
			}
			continue
		}
		if value, ok := strings.CutPrefix(line, "data:"); ok {
			if event.Len() > 0 {
				event.WriteByte('\n')
			}
			event.WriteString(strings.TrimPrefix(value, " "))
		}
	}
	if err := scanner.Err(); err != nil {
		return envelope{}, fmt.Errorf("read event stream: %w", err)
	}
	if answer, ok := flush(); ok {
		return answer, nil
	}
	return envelope{}, errors.New("the event stream ended without the answer")
}

// EncodeHeaderValue carries a name that is not plain printable ASCII in the
// =?base64?...?= form of the Streamable HTTP transport.
func EncodeHeaderValue(value string) string {
	plain := value != "" && value == strings.TrimSpace(value) && !strings.HasPrefix(value, "=?base64?")
	for _, r := range value {
		if r < 0x20 || r > 0x7e {
			plain = false
			break
		}
	}
	if plain {
		return value
	}
	return "=?base64?" + base64.StdEncoding.EncodeToString([]byte(value)) + "?="
}
