package domain

import (
	"encoding/json"
	"fmt"
	"regexp"
	"slices"
	"strings"
)

// JSON-RPC error codes of the A2A SDK.
const (
	A2ACodeParse                = -32700
	A2ACodeInvalidRequest       = -32600
	A2ACodeMethodNotFound       = -32601
	A2ACodeInvalidParams        = -32602
	A2ACodeInternal             = -32603
	A2ACodeTaskNotFound         = -32001
	A2ACodeUnsupportedOperation = -32004
	A2ACodeVersionNotSupported  = -32009
)

// A2AProtocolVersion is the A2A-Version this handler serves.
const A2AProtocolVersion = "1.0"

// A2ARPCError is a JSON-RPC error object. Data is left out when nil
// (model_dump(exclude_none=True)).
type A2ARPCError struct {
	Code    int
	Message string
	Data    any
}

func (e *A2ARPCError) Error() string { return e.Message }

// JSON is the error object.
func (e *A2ARPCError) JSON() A2AJSON {
	o := A2AJSON{{Key: "code", Value: e.Code}, {Key: "message", Value: e.Message}}
	if e.Data != nil {
		o = append(o, A2AMember{Key: "data", Value: e.Data})
	}
	return o
}

// a2aTyped is an A2AError: its data is a google.rpc.ErrorInfo with the reason.
func a2aTyped(code int, reason, message string) *A2ARPCError {
	return &A2ARPCError{Code: code, Message: message, Data: []any{A2AJSON{
		{Key: "@type", Value: "type.googleapis.com/google.rpc.ErrorInfo"},
		{Key: "reason", Value: reason},
		{Key: "domain", Value: "a2a-protocol.org"},
		{Key: "metadata", Value: A2AJSON{}},
	}}}
}

// A2AInvalidParams is a2a.utils.errors.InvalidParamsError.
func A2AInvalidParams(message string) *A2ARPCError {
	return a2aTyped(A2ACodeInvalidParams, "INVALID_PARAMS", message)
}

// A2AInvalidRequest is a2a.utils.errors.InvalidRequestError.
func A2AInvalidRequest(message string) *A2ARPCError {
	return a2aTyped(A2ACodeInvalidRequest, "INVALID_REQUEST", message)
}

// A2AInternal is a2a.utils.errors.InternalError.
func A2AInternal(message string) *A2ARPCError {
	return a2aTyped(A2ACodeInternal, "INTERNAL_ERROR", message)
}

// A2AUnsupportedOperation is UnsupportedOperationError.
func A2AUnsupportedOperation(message string) *A2ARPCError {
	return a2aTyped(A2ACodeUnsupportedOperation, "UNSUPPORTED_OPERATION", message)
}

// A2AUnavailable answers a method whose task system is not wired yet.
func A2AUnavailable(method string) *A2ARPCError {
	return A2AUnsupportedOperation(method + " is not available yet")
}

// A2AParseError is the dispatcher's JSONParseError: message is str(JSONDecodeError).
func A2AParseError(message string) *A2ARPCError {
	return &A2ARPCError{Code: A2ACodeParse, Message: message}
}

// A2AMethodNotFound is the dispatcher's MethodNotFoundError.
func A2AMethodNotFound() *A2ARPCError {
	return &A2ARPCError{Code: A2ACodeMethodNotFound, Message: "Method not found"}
}

func a2aBadRequest(data any) *A2ARPCError {
	return &A2ARPCError{Code: A2ACodeInvalidRequest, Message: "Invalid Request", Data: data}
}

// A2ARPCResult is JSONRPC20Response(result=..., _id=...).data.
func A2ARPCResult(id, result any) A2AJSON {
	return A2AJSON{{Key: "result", Value: result}, {Key: "id", Value: id}, {Key: "jsonrpc", Value: "2.0"}}
}

// A2ARPCFailure is build_error_response.
func A2ARPCFailure(id any, e *A2ARPCError) A2AJSON {
	return A2AJSON{{Key: "error", Value: e.JSON()}, {Key: "id", Value: id}, {Key: "jsonrpc", Value: "2.0"}}
}

// A2ARPCRequest is one framed JSON-RPC request.
type A2ARPCRequest struct {
	// ID is a string, an integer (json.Number), a bool or nil.
	ID     any
	Method string
	Params any
	// HasParams is false when the request carried no "params".
	HasParams bool
}

func a2aIsInt(v any) bool {
	switch x := v.(type) {
	case bool, int:
		return true
	case json.Number:
		return !a2aIsFloatLiteral(x)
	}
	return false
}

func a2aSet(keys []string) string {
	if len(keys) == 0 {
		return "set()"
	}
	slices.Sort(keys)
	q := make([]string, len(keys))
	for i, k := range keys {
		q[i] = a2aPyQuote(k)
	}
	return "{" + strings.Join(q, ", ") + "}"
}

// a2aCheckRequest is JSONRPC20Request.from_data for one object.
func a2aCheckRequest(d A2AJSON) string {
	has := map[string]bool{}
	var extra []string
	for _, m := range d {
		has[m.Key] = true
		switch m.Key {
		case "jsonrpc", "method", "params", "id":
		default:
			extra = append(extra, m.Key)
		}
	}
	var missed []string
	for _, k := range []string{"jsonrpc", "method"} {
		if !has[k] {
			missed = append(missed, k)
		}
	}
	if len(extra) > 0 || len(missed) > 0 {
		return fmt.Sprintf("Invalid request. Extra fields: %s, Missed fields: %s", a2aSet(extra), a2aSet(missed))
	}
	method, _ := d.Get("method")
	name, ok := method.(string)
	if !ok {
		return "Method should be string"
	}
	if strings.HasPrefix(name, "rpc.") {
		return "Method names that begin with the word rpc followed by a period character (U+002E or ASCII 46) are reserved for rpc-internal methods and extensions and MUST NOT be used for anything else."
	}
	if params, _ := d.Get("params"); params != nil {
		switch params.(type) {
		case A2AJSON, []any:
		default:
			return "Incorrect params " + a2aPyStr(params)
		}
	}
	if id, _ := d.Get("id"); id != nil {
		if _, isStr := id.(string); !isStr && !a2aIsInt(id) {
			return "id should be string or integer"
		}
	}
	return ""
}

// A2AFrame is the dispatcher's framing of a decoded body: the request, or the
// error response to answer with.
func A2AFrame(body any) (A2ARPCRequest, A2AJSON) {
	var requestID any
	d, isObject := body.(A2AJSON)
	if isObject {
		if id, _ := d.Get("id"); id != nil {
			if _, isStr := id.(string); isStr || a2aIsInt(id) {
				requestID = id
			}
		}
	}
	items := []any{body}
	list, isBatch := body.([]any)
	if isBatch {
		items = list
	}
	if len(items) == 0 {
		return A2ARPCRequest{}, A2ARPCFailure(requestID, a2aBadRequest("[] value is not accepted"))
	}
	for _, it := range items {
		if _, ok := it.(A2AJSON); !ok {
			return A2ARPCRequest{}, A2ARPCFailure(requestID, a2aBadRequest("Each request should be an object (dict)"))
		}
	}
	for _, it := range items {
		if msg := a2aCheckRequest(it.(A2AJSON)); msg != "" {
			return A2ARPCRequest{}, A2ARPCFailure(requestID, a2aBadRequest(msg))
		}
	}
	if isBatch {
		return A2ARPCRequest{}, A2ARPCFailure(requestID, &A2ARPCError{Code: A2ACodeInvalidRequest, Message: "Batch requests are not supported"})
	}
	if v, _ := d.Get("jsonrpc"); v != "2.0" {
		return A2ARPCRequest{}, A2ARPCFailure(requestID, &A2ARPCError{Code: A2ACodeInvalidRequest, Message: "Invalid request: 'jsonrpc' must be exactly '2.0'"})
	}
	id, _ := d.Get("id")
	method, _ := d.Get("method")
	req := A2ARPCRequest{ID: id, Method: method.(string)}
	req.Params, req.HasParams = d.Get("params")
	if req.Method == "" {
		return req, A2ARPCFailure(id, &A2ARPCError{Code: A2ACodeInvalidRequest, Message: "Method is required"})
	}
	return req, nil
}

type a2aRequestType struct {
	name string
	// fields are the json names in declaration order; the proto name is their snake case.
	fields []string
}

func a2aMethodTypes() map[string]a2aRequestType {
	return map[string]a2aRequestType{
		"SendMessage":                      {"SendMessageRequest", []string{"tenant", "message", "configuration", "metadata"}},
		"SendStreamingMessage":             {"SendMessageRequest", []string{"tenant", "message", "configuration", "metadata"}},
		"GetTask":                          {"GetTaskRequest", []string{"tenant", "id", "historyLength"}},
		"ListTasks":                        {"ListTasksRequest", []string{"tenant", "contextId", "status", "pageSize", "pageToken", "historyLength", "statusTimestampAfter", "includeArtifacts"}},
		"CancelTask":                       {"CancelTaskRequest", []string{"tenant", "id", "metadata"}},
		"CreateTaskPushNotificationConfig": {"TaskPushNotificationConfig", []string{"tenant", "id", "taskId", "url", "token", "authentication"}},
		"GetTaskPushNotificationConfig":    {"GetTaskPushNotificationConfigRequest", []string{"tenant", "taskId", "id"}},
		"ListTaskPushNotificationConfigs":  {"ListTaskPushNotificationConfigsRequest", []string{"tenant", "taskId", "pageSize", "pageToken"}},
		"DeleteTaskPushNotificationConfig": {"DeleteTaskPushNotificationConfigRequest", []string{"tenant", "taskId", "id"}},
		"SubscribeToTask":                  {"SubscribeToTaskRequest", []string{"tenant", "id"}},
		"GetExtendedAgentCard":             {"GetExtendedAgentCardRequest", []string{"tenant"}},
	}
}

// a2aStringFields are the top-level string fields of the request messages.
func a2aStringFields() map[string]bool {
	return map[string]bool{"tenant": true, "id": true, "contextId": true, "pageToken": true, "taskId": true, "url": true, "token": true}
}

var a2aExtensionName = regexp.MustCompile(`^\[[a-zA-Z0-9._]*\]$`)

func a2aSnake(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r >= 'A' && r <= 'Z' {
			b.WriteByte('_')
			r += 'a' - 'A'
		}
		b.WriteRune(r)
	}
	return b.String()
}

func (t a2aRequestType) field(name string) (string, bool) {
	for _, f := range t.fields {
		if name == f || name == a2aSnake(f) {
			return f, true
		}
	}
	return "", false
}

func (t a2aRequestType) unknown(name string) string {
	q := make([]string, len(t.fields))
	for i, f := range t.fields {
		q[i] = a2aPyQuote(f)
	}
	if a2aExtensionName.MatchString(name) {
		return fmt.Sprintf("Message type lf.a2a.v1.%s does not have extensions at %s", t.name, t.name)
	}
	return fmt.Sprintf("Message type \"lf.a2a.v1.%s\" has no field named \"%s\" at \"%s\".\n Available Fields(except extensions): \"[%s]\"",
		t.name, name, t.name, strings.Join(q, ", "))
}

func a2aFieldFailure(name, reason string) string {
	return fmt.Sprintf("Failed to parse %s field: %s.", name, reason)
}

// A2AKnownMethod reports whether the dispatcher routes method.
func A2AKnownMethod(method string) bool { _, ok := a2aMethodTypes()[method]; return ok }

// A2AParseParams is ParseDict(params, Request()) for the method's request
// message: the InvalidParamsError data when it fails. It checks the field
// names and the top-level string fields; nested messages are not checked.
func A2AParseParams(method string, params any, present bool) *A2ARPCError {
	t := a2aMethodTypes()[method]
	if msg := t.parse(params, present); msg != "" {
		return &A2ARPCError{Code: A2ACodeInvalidParams, Message: "Invalid params", Data: msg}
	}
	return nil
}

func (t a2aRequestType) parse(params any, present bool) string {
	if !present {
		return ""
	}
	switch p := params.(type) {
	case A2AJSON:
		for _, m := range p {
			f, ok := t.field(m.Key)
			if !ok {
				return t.unknown(m.Key)
			}
			if m.Value == nil || !a2aStringFields()[f] {
				continue
			}
			if _, isStr := m.Value.(string); !isStr {
				return a2aFieldFailure(m.Key, fmt.Sprintf("expected string or bytes-like object, got '%s'", a2aPyType(m.Value)))
			}
		}
		return ""
	case []any:
		for _, e := range p {
			switch name := e.(type) {
			case string:
				if _, ok := t.field(name); ok {
					return a2aFieldFailure(name, "list indices must be integers or slices, not str")
				}
				return t.unknown(name)
			case A2AJSON, []any:
				return a2aFieldFailure(a2aPyStr(name), fmt.Sprintf("unhashable type: '%s'", a2aPyType(name)))
			default:
				return a2aFieldFailure(a2aPyStr(name), fmt.Sprintf("expected string or bytes-like object, got '%s'", a2aPyType(name)))
			}
		}
		return ""
	case string:
		for _, r := range p {
			return t.unknown(string(r))
		}
		return ""
	}
	return fmt.Sprintf("'%s' object is not iterable", a2aPyType(params))
}

var a2aVersion = regexp.MustCompile(`(?i)^v?(?:[0-9]+!)?([0-9]+)(?:\.[0-9]+)*` +
	`(?:[-_.]?(?:alpha|a|beta|b|preview|pre|c|rc)[-_.]?[0-9]*)?` +
	`(?:-[0-9]+|[-_.]?(?:post|rev|r)[-_.]?[0-9]*)?` +
	`(?:[-_.]?dev[-_.]?[0-9]*)?` +
	`(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?$`)

// A2ACheckVersion is validate_version("1.0") over the A2A-Version header: a
// missing one is 0.3; any 1.x is served.
func A2ACheckVersion(header string) *A2ARPCError {
	actual := header
	if actual == "" {
		actual = "0.3"
	}
	if actual == A2AProtocolVersion {
		return nil
	}
	if m := a2aVersion.FindStringSubmatch(a2aPyStrip(actual)); m != nil && strings.TrimLeft(m[1], "0") == "1" {
		return nil
	}
	return a2aTyped(A2ACodeVersionNotSupported, "VERSION_NOT_SUPPORTED",
		fmt.Sprintf("A2A version '%s' is not supported by this handler. Expected version '%s'.", actual, A2AProtocolVersion))
}
