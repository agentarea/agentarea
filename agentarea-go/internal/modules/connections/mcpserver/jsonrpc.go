// Package mcpserver serves MCP over stateless Streamable HTTP with JSON
// responses: the platform mounts (/mcp, /mcp/w/{workspace}), a client's
// bundle (/mcp/clients/{id}, /client-mcp/{id}) and an API connection as an
// MCP server. It speaks the initialize handshake (2024-11-05..2025-11-25) and
// the 2026-07-28 per-request envelope, as the Python MCP SDK does.
package mcpserver

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"strings"
	"unicode/utf8"
)

// JSON-RPC and MCP error codes.
const (
	CodeParseError             = -32700
	CodeInvalidRequest         = -32600
	CodeMethodNotFound         = -32601
	CodeInvalidParams          = -32602
	CodeInternalError          = -32603
	CodeHeaderMismatch         = -32020
	CodeUnsupportedProtocolVer = -32022
)

// HandshakeVersions are the revisions initialize negotiates.
func HandshakeVersions() []string {
	return []string{"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
}

// ModernVersions are the revisions whose requests carry their own envelope.
func ModernVersions() []string { return []string{"2026-07-28"} }

// LatestHandshakeVersion is the counter-offer to an initialize naming a revision not served.
const LatestHandshakeVersion = "2025-11-25"

// Envelope keys and headers of the 2026-07-28 wire.
const (
	MetaProtocolVersion    = "io.modelcontextprotocol/protocolVersion"
	MetaClientCapabilities = "io.modelcontextprotocol/clientCapabilities"
	MetaServerInfo         = "io.modelcontextprotocol/serverInfo"
	HeaderProtocolVersion  = "MCP-Protocol-Version"
	HeaderMethod           = "Mcp-Method"
	HeaderName             = "Mcp-Name"
)

// Extension ids advertised under capabilities.extensions.
const (
	AppsExtension   = "io.modelcontextprotocol/ui"
	EventsExtension = "io.modelcontextprotocol/events"
)

// NameBearingParam is the params key Mcp-Name mirrors for method.
func NameBearingParam(method string) (string, bool) {
	switch method {
	case "tools/call", "prompts/get":
		return "name", true
	case "resources/read":
		return "uri", true
	}
	return "", false
}

// Error is a JSON-RPC error a handler answers with.
type Error struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

func (e *Error) Error() string { return e.Message }

// Request is one decoded JSON-RPC message.
type Request struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// IsNotification is a message without an id.
func (r Request) IsNotification() bool { return len(r.ID) == 0 }

type response struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Result  any             `json:"result,omitempty"`
	Error   *Error          `json:"error,omitempty"`
}

func idOrNull(id json.RawMessage) json.RawMessage {
	if len(id) == 0 {
		return json.RawMessage("null")
	}
	return id
}

// WriteError writes a JSON-RPC error body with status.
func WriteError(w http.ResponseWriter, status int, id json.RawMessage, e *Error) {
	writeJSON(w, status, response{JSONRPC: "2.0", ID: idOrNull(id), Error: e})
}

func writeResult(w http.ResponseWriter, id json.RawMessage, result any) {
	writeJSON(w, http.StatusOK, response{JSONRPC: "2.0", ID: idOrNull(id), Result: result})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	body, err := json.Marshal(v)
	if err != nil {
		body = []byte(`{"jsonrpc":"2.0","id":null,"error":{"code":-32603,"message":"Internal error"}}`)
		status = http.StatusInternalServerError
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// PeekMethod is the method and id of a body holding one JSON-RPC object;
// empty when it holds anything else.
func PeekMethod(body []byte) (string, json.RawMessage) {
	var r Request
	if json.Unmarshal(body, &r) != nil {
		return "", nil
	}
	return r.Method, r.ID
}

// DecodeHeaderValue is decode_header_value: a "=?base64?...?=" value is
// decoded as UTF-8; a malformed one is ok false.
func DecodeHeaderValue(v string) (string, bool) {
	const pre, suf = "=?base64?", "?="
	if !strings.HasPrefix(v, pre) || !strings.HasSuffix(v, suf) || len(v) < len(pre)+len(suf) {
		return v, true
	}
	payload := v[len(pre) : len(v)-len(suf)]
	raw, err := base64.StdEncoding.Strict().DecodeString(payload)
	if err != nil || base64.StdEncoding.EncodeToString(raw) != payload || !utf8.Valid(raw) {
		return "", false
	}
	return string(raw), true
}

// httpStatusFor is ERROR_CODE_HTTP_STATUS, consulted on the 2026-07-28 wire.
func httpStatusFor(code int) int {
	switch code {
	case CodeParseError, CodeInvalidRequest, CodeInvalidParams, CodeHeaderMismatch, CodeUnsupportedProtocolVer:
		return http.StatusBadRequest
	case CodeMethodNotFound:
		return http.StatusNotFound
	}
	return http.StatusOK
}
