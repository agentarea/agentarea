package mcpserver

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"slices"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mcpserve"
)

const maxBody = 16 << 20

// Icon is one serverInfo icon.
type Icon struct {
	Src      string   `json:"src"`
	MimeType string   `json:"mimeType,omitempty"`
	Sizes    []string `json:"sizes,omitempty"`
}

// Info is what initialize and server/discover report about a server.
type Info struct {
	Name         string
	Title        string
	Description  string
	Version      string
	WebsiteURL   string
	Icons        []Icon
	Instructions string
	// Resources and Prompts advertise those capabilities; a backend that is
	// not a ResourceBackend then lists none.
	Resources bool
	Prompts   bool
	// Extensions are advertised under capabilities.extensions, each with its settings.
	Extensions map[string]map[string]any
}

// Tool is a tools/list entry: the contract's fields plus _meta (MCP Apps).
type Tool struct {
	mcpserve.Tool
	Meta map[string]any `json:"_meta,omitempty"`
}

// Backend is what one request lists and calls.
type Backend interface {
	ListTools(ctx context.Context) ([]Tool, error)
	// CallTool returns the tools/call result object (a mcpserve.Result or
	// an upstream's result as received).
	CallTool(ctx context.Context, name string, args json.RawMessage) (any, error)
}

// ResourceBackend serves resources/list and resources/read.
type ResourceBackend interface {
	ListResources(ctx context.Context) ([]json.RawMessage, error)
	// ReadResource is the resources/read result; ok false for a URI it does not serve.
	ReadResource(ctx context.Context, uri string) (json.RawMessage, bool, error)
}

// Refusal is a handler's refusal: Python raised it as a plain exception,
// which the handshake wire answers with code 0 and its message.
type Refusal struct{ Msg string }

func (e *Refusal) Error() string { return e.Msg }

// Endpoint serves one MCP mount. Backend resolves the request's backend
// after the auth middleware ran.
type Endpoint struct {
	Info    Info
	Backend func(r *http.Request) (Backend, error)
	// Events serves the events extension; nil neither advertises nor serves it.
	Events *EventsHandler
	Log    *slog.Logger
}

func (e *Endpoint) log() *slog.Logger {
	if e.Log == nil {
		return slog.New(slog.DiscardHandler)
	}
	return e.Log
}

func (e *Endpoint) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		WriteError(w, http.StatusMethodNotAllowed, json.RawMessage(`"server-error"`), &Error{Code: -32000, Message: "Method Not Allowed"})
		return
	}
	if mt, _, err := mime.ParseMediaType(r.Header.Get("Content-Type")); err != nil || mt != "application/json" {
		WriteError(w, http.StatusUnsupportedMediaType, json.RawMessage(`"server-error"`),
			&Error{Code: CodeInvalidRequest, Message: "Unsupported Media Type: Content-Type must be application/json"})
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, maxBody+1))
	if err != nil || len(body) > maxBody {
		WriteError(w, http.StatusBadRequest, nil, &Error{Code: CodeParseError, Message: "Parse error"})
		return
	}
	trimmed := bytes.TrimSpace(body)
	if len(trimmed) > 0 && trimmed[0] == '[' {
		WriteError(w, http.StatusBadRequest, nil, &Error{Code: CodeInvalidRequest, Message: "Batch requests are not supported"})
		return
	}
	var req Request
	if err := json.Unmarshal(trimmed, &req); err != nil {
		WriteError(w, http.StatusBadRequest, nil, &Error{Code: CodeParseError, Message: "Parse error"})
		return
	}
	if req.JSONRPC != "2.0" || req.Method == "" {
		WriteError(w, http.StatusBadRequest, req.ID, &Error{Code: CodeInvalidRequest, Message: "Invalid Request"})
		return
	}
	if req.IsNotification() {
		w.WriteHeader(http.StatusAccepted)
		return
	}
	params := map[string]any{}
	if len(req.Params) > 0 && string(req.Params) != "null" {
		dec := json.NewDecoder(bytes.NewReader(req.Params))
		dec.UseNumber()
		if dec.Decode(&params) != nil {
			WriteError(w, http.StatusOK, req.ID, &Error{Code: CodeInvalidParams, Message: "Invalid request parameters"})
			return
		}
	}
	modern := isModern(params)
	if modern {
		if rej := classify(params, req.Method, r.Header); rej != nil {
			WriteError(w, httpStatusFor(rej.Code), req.ID, rej)
			return
		}
	}
	result, rpcErr := e.dispatch(r, req, params, modern)
	if rpcErr != nil {
		status := http.StatusOK
		if modern {
			status = httpStatusFor(rpcErr.Code)
		}
		WriteError(w, status, req.ID, rpcErr)
		return
	}
	if modern {
		result = e.stamp(result)
	}
	writeResult(w, req.ID, result)
}

func isModern(params map[string]any) bool {
	meta, ok := params["_meta"].(map[string]any)
	if !ok {
		return false
	}
	_, ok = meta[MetaProtocolVersion]
	return ok
}

// classify is classify_inbound_request: the envelope, the routing headers,
// then the version.
func classify(params map[string]any, method string, h http.Header) *Error {
	meta, _ := params["_meta"].(map[string]any)
	var missing []string
	for _, k := range []string{MetaProtocolVersion, MetaClientCapabilities} {
		if _, ok := meta[k]; !ok {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		msg := "params._meta is missing the required envelope key(s): " + missing[0]
		for _, m := range missing[1:] {
			msg += ", " + m
		}
		return &Error{Code: CodeInvalidParams, Message: msg}
	}
	version := meta[MetaProtocolVersion]
	if vh := h.Values(HeaderProtocolVersion); len(vh) != 1 || version != vh[0] {
		return &Error{Code: CodeHeaderMismatch, Message: HeaderProtocolVersion + " header does not match the request envelope's protocol version"}
	}
	if mh := h.Values(HeaderMethod); len(mh) != 1 || mh[0] != method {
		return &Error{Code: CodeHeaderMismatch, Message: HeaderMethod + " header does not match the request body's method"}
	}
	if key, ok := NameBearingParam(method); ok {
		if bodyValue, present := params[key]; present && bodyValue != nil {
			decoded, ok := DecodeHeaderValue(h.Get(HeaderName))
			if !ok || h.Get(HeaderName) == "" || decoded != bodyValue {
				return &Error{Code: CodeHeaderMismatch, Message: HeaderName + " header does not match the request body's '" + key + "' parameter"}
			}
		}
	}
	s, ok := version.(string)
	if !ok {
		return &Error{Code: CodeInvalidParams, Message: "params._meta protocol version must be a string"}
	}
	if !slices.Contains(ModernVersions(), s) {
		return &Error{Code: CodeUnsupportedProtocolVer, Message: "Unsupported protocol version",
			Data: map[string]any{"supported": ModernVersions(), "requested": s}}
	}
	return nil
}

func (e *Endpoint) serverInfo() map[string]any {
	info := map[string]any{"name": e.Info.Name, "version": e.Info.Version}
	if e.Info.Title != "" {
		info["title"] = e.Info.Title
	}
	if e.Info.Description != "" {
		info["description"] = e.Info.Description
	}
	if e.Info.WebsiteURL != "" {
		info["websiteUrl"] = e.Info.WebsiteURL
	}
	if len(e.Info.Icons) > 0 {
		info["icons"] = e.Info.Icons
	}
	return info
}

func (e *Endpoint) capabilities() map[string]any {
	caps := map[string]any{"tools": map[string]any{"listChanged": false}}
	if e.Info.Resources {
		caps["resources"] = map[string]any{"subscribe": false, "listChanged": false}
	}
	if e.Info.Prompts {
		caps["prompts"] = map[string]any{"listChanged": false}
	}
	ext := map[string]any{}
	for k, v := range e.Info.Extensions {
		ext[k] = v
	}
	if e.Events != nil {
		ext[EventsExtension] = eventsSettings()
		caps["events"] = eventsSettings()
	}
	if len(ext) > 0 {
		caps["extensions"] = ext
	}
	return caps
}

func (e *Endpoint) stamp(result any) any {
	raw, err := json.Marshal(result)
	if err != nil {
		return result
	}
	m := map[string]any{}
	if json.Unmarshal(raw, &m) != nil {
		return result
	}
	if _, ok := m["resultType"]; !ok {
		m["resultType"] = "complete"
	}
	meta, _ := m["_meta"].(map[string]any)
	if meta == nil {
		meta = map[string]any{}
	}
	if meta[MetaServerInfo] == nil {
		meta[MetaServerInfo] = e.serverInfo()
	}
	m["_meta"] = meta
	return m
}

func (e *Endpoint) dispatch(r *http.Request, req Request, params map[string]any, modern bool) (any, *Error) {
	switch req.Method {
	case "initialize":
		requested, _ := params["protocolVersion"].(string)
		version := LatestHandshakeVersion
		if slices.Contains(HandshakeVersions(), requested) {
			version = requested
		}
		out := map[string]any{"protocolVersion": version, "capabilities": e.capabilities(), "serverInfo": e.serverInfo()}
		if e.Info.Instructions != "" {
			out["instructions"] = e.Info.Instructions
		}
		return out, nil
	case "ping":
		return map[string]any{}, nil
	case "server/discover":
		if !modern {
			return nil, &Error{Code: CodeMethodNotFound, Message: "Method not found"}
		}
		out := map[string]any{"supportedVersions": ModernVersions(), "capabilities": e.capabilities()}
		if e.Info.Instructions != "" {
			out["instructions"] = e.Info.Instructions
		}
		return out, nil
	case "prompts/list":
		if !e.Info.Prompts {
			return nil, &Error{Code: CodeMethodNotFound, Message: "Method not found"}
		}
		return map[string]any{"prompts": []any{}}, nil
	case "events/list", "events/poll", "events/subscribe", "events/unsubscribe":
		if e.Events == nil {
			return nil, &Error{Code: CodeMethodNotFound, Message: "Method not found"}
		}
		return e.serveEvents(r, req, modern)
	case "tools/list", "tools/call", "resources/list", "resources/templates/list", "resources/read":
	default:
		return nil, &Error{Code: CodeMethodNotFound, Message: "Method not found"}
	}
	b, err := e.Backend(r)
	if err != nil {
		return nil, e.rpcError(r.Context(), req.Method, err, modern)
	}
	ctx := r.Context()
	switch req.Method {
	case "tools/list":
		tools, err := b.ListTools(ctx)
		if err != nil {
			return nil, e.rpcError(ctx, req.Method, err, modern)
		}
		if tools == nil {
			tools = []Tool{}
		}
		return map[string]any{"tools": tools}, nil
	case "tools/call":
		name, _ := params["name"].(string)
		if name == "" {
			return nil, &Error{Code: CodeInvalidParams, Message: "Invalid request parameters"}
		}
		args := json.RawMessage("{}")
		if a, ok := params["arguments"]; ok && a != nil {
			if _, isObj := a.(map[string]any); !isObj {
				return nil, &Error{Code: CodeInvalidParams, Message: "Invalid request parameters"}
			}
			raw, err := json.Marshal(a)
			if err != nil {
				return nil, &Error{Code: CodeInvalidParams, Message: "Invalid request parameters"}
			}
			args = raw
		}
		res, err := b.CallTool(ctx, name, args)
		if err != nil {
			return nil, e.rpcError(ctx, req.Method, err, modern)
		}
		return res, nil
	}
	rb, ok := b.(ResourceBackend)
	switch {
	case !ok && !e.Info.Resources:
		return nil, &Error{Code: CodeMethodNotFound, Message: "Method not found"}
	case req.Method == "resources/templates/list":
		return map[string]any{"resourceTemplates": []any{}}, nil
	case req.Method == "resources/list":
		if !ok {
			return map[string]any{"resources": []any{}}, nil
		}
		res, err := rb.ListResources(ctx)
		if err != nil {
			return nil, e.rpcError(ctx, req.Method, err, modern)
		}
		if res == nil {
			res = []json.RawMessage{}
		}
		return map[string]any{"resources": res}, nil
	}
	uri, _ := params["uri"].(string)
	if uri == "" {
		return nil, &Error{Code: CodeInvalidParams, Message: "Invalid request parameters"}
	}
	if ok {
		res, found, err := rb.ReadResource(ctx, uri)
		if err != nil {
			return nil, e.rpcError(ctx, req.Method, err, modern)
		}
		if found {
			return res, nil
		}
	}
	return nil, &Error{Code: CodeInvalidParams, Message: "Unknown resource: " + uri, Data: map[string]any{"uri": uri}}
}

func (e *Endpoint) rpcError(ctx context.Context, method string, err error, modern bool) *Error {
	var rpc *Error
	if errors.As(err, &rpc) {
		return rpc
	}
	var refusal *Refusal
	if errors.As(err, &refusal) {
		if modern {
			return &Error{Code: CodeInternalError, Message: refusal.Msg}
		}
		return &Error{Code: 0, Message: refusal.Msg}
	}
	e.log().ErrorContext(ctx, "MCP handler failed", "method", method, "error", err)
	return &Error{Code: CodeInternalError, Message: "Internal error"}
}
