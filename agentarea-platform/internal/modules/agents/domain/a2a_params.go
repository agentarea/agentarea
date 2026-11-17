package domain

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"strconv"
)

// A2ACodeTaskNotCancelable is the SDK's TaskNotCancelableError code.
const A2ACodeTaskNotCancelable = -32002

// A2ATaskNotFound is TaskNotFoundError.
func A2ATaskNotFound(message string) *A2ARPCError {
	return a2aTyped(A2ACodeTaskNotFound, "TASK_NOT_FOUND", message)
}

// A2ATaskNotCancelable is TaskNotCancelableError.
func A2ATaskNotCancelable(message string) *A2ARPCError {
	return a2aTyped(A2ACodeTaskNotCancelable, "TASK_NOT_CANCELABLE", message)
}

// A2AViolation is one field a request left out (ValidationDetail).
type A2AViolation struct{ Field, Message string }

// A2AValidationFailed is validate_proto_required_fields' InvalidParamsError:
// the ErrorInfo carries the violations, and a BadRequest lists them.
func A2AValidationFailed(violations []A2AViolation) *A2ARPCError {
	errs := make([]any, len(violations))
	fields := make([]any, len(violations))
	for i, v := range violations {
		errs[i] = A2AJSON{{Key: "field", Value: v.Field}, {Key: "message", Value: v.Message}}
		fields[i] = A2AJSON{{Key: "field", Value: v.Field}, {Key: "description", Value: v.Message}}
	}
	return &A2ARPCError{Code: A2ACodeInvalidParams, Message: "Validation failed", Data: []any{
		A2AJSON{
			{Key: "@type", Value: "type.googleapis.com/google.rpc.ErrorInfo"},
			{Key: "reason", Value: "INVALID_PARAMS"},
			{Key: "domain", Value: "a2a-protocol.org"},
			{Key: "metadata", Value: A2AJSON{{Key: "errors", Value: errs}}},
		},
		A2AJSON{
			{Key: "@type", Value: "type.googleapis.com/google.rpc.BadRequest"},
			{Key: "fieldViolations", Value: fields},
		},
	}}
}

func a2aRequired(field string) A2AViolation {
	return A2AViolation{Field: field, Message: "Field is required."}
}

// a2aField reads a request field by its JSON name or its proto name.
func a2aField(o A2AJSON, name string) (any, bool) {
	if v, ok := o.Get(name); ok {
		return v, true
	}
	return o.Get(a2aSnake(name))
}

func a2aObject(o A2AJSON, name string) (A2AJSON, bool) {
	v, _ := a2aField(o, name)
	obj, ok := v.(A2AJSON)
	return obj, ok
}

func a2aText(o A2AJSON, name string) string {
	v, _ := a2aField(o, name)
	s, _ := v.(string)
	return s
}

func a2aInvalidField(name, reason string) *A2ARPCError {
	return &A2ARPCError{Code: A2ACodeInvalidParams, Message: "Invalid params", Data: a2aFieldFailure(name, reason)}
}

func a2aParams(params any) A2AJSON {
	o, _ := params.(A2AJSON)
	return o
}

// A2APushConfig is a TaskPushNotificationConfig a client sent.
type A2APushConfig struct {
	ID, TaskID, URL, Token string
	// Authentication is set when the client sent an authentication scheme.
	Authentication bool
}

func a2aPush(o A2AJSON) A2APushConfig {
	auth, _ := a2aField(o, "authentication")
	return A2APushConfig{
		ID: a2aText(o, "id"), TaskID: a2aText(o, "taskId"), URL: a2aText(o, "url"), Token: a2aText(o, "token"), Authentication: auth != nil,
	}
}

// A2APushParams is CreateTaskPushNotificationConfig's params: url is required.
func A2APushParams(params any) (A2APushConfig, *A2ARPCError) {
	cfg := a2aPush(a2aParams(params))
	if cfg.URL == "" {
		return cfg, A2AValidationFailed([]A2AViolation{a2aRequired("url")})
	}
	return cfg, nil
}

// A2ATaskRef is the task (and config) id a task method names.
type A2ATaskRef struct{ TaskID, ConfigID string }

// A2AIDParams is the params of GetTask, CancelTask and SubscribeToTask: id is required.
func A2AIDParams(params any) (A2ATaskRef, *A2ARPCError) {
	id := a2aText(a2aParams(params), "id")
	if id == "" {
		return A2ATaskRef{}, A2AValidationFailed([]A2AViolation{a2aRequired("id")})
	}
	return A2ATaskRef{TaskID: id}, nil
}

// A2AConfigParams is the params of Get and DeleteTaskPushNotificationConfig:
// task_id and id are required; of ListTaskPushNotificationConfigs only task_id.
func A2AConfigParams(params any, withID bool) (A2ATaskRef, *A2ARPCError) {
	o := a2aParams(params)
	ref := A2ATaskRef{TaskID: a2aText(o, "taskId"), ConfigID: a2aText(o, "id")}
	var missing []A2AViolation
	if ref.TaskID == "" {
		missing = append(missing, a2aRequired("task_id"))
	}
	if withID && ref.ConfigID == "" {
		missing = append(missing, a2aRequired("id"))
	}
	if len(missing) > 0 {
		return ref, A2AValidationFailed(missing)
	}
	return ref, nil
}

// A2ASendRequest is a SendMessageRequest.
type A2ASendRequest struct {
	ContextID, TaskID string
	Parts             []A2APart
	PartCount         int
	Metadata          A2AJSON
	Push              *A2APushConfig
}

// A2ASendParams is SendMessageRequest parsed and checked for its required
// fields: the message, with its id, role and parts.
func A2ASendParams(params any) (A2ASendRequest, *A2ARPCError) {
	var out A2ASendRequest
	o := a2aParams(params)
	msgValue, hasMessage := a2aField(o, "message")
	if msgValue != nil {
		if _, ok := msgValue.(A2AJSON); !ok {
			return out, a2aInvalidField("message", "Message must be a dict")
		}
	}
	msg, _ := msgValue.(A2AJSON)
	if !hasMessage || msgValue == nil {
		return out, A2AValidationFailed([]A2AViolation{a2aRequired("message")})
	}
	var missing []A2AViolation
	if a2aText(msg, "messageId") == "" {
		missing = append(missing, a2aRequired("message.message_id"))
	}
	roleValue, _ := a2aField(msg, "role")
	role, rerr := a2aRole(roleValue)
	if rerr != nil {
		return out, rerr
	}
	if role == 0 {
		missing = append(missing, a2aRequired("message.role"))
	}
	partsValue, _ := a2aField(msg, "parts")
	list, isList := partsValue.([]any)
	if partsValue != nil && !isList {
		return out, a2aInvalidField("parts", "Parts must be a list")
	}
	if len(list) == 0 {
		missing = append(missing, A2AViolation{Field: "message.parts", Message: "Field must contain at least one element."})
	}
	if len(missing) > 0 {
		return out, A2AValidationFailed(missing)
	}
	for _, p := range list {
		part, ok := p.(A2AJSON)
		if !ok {
			return out, a2aInvalidField("parts", "Parts must be dicts")
		}
		if text, isText := part.Get("text"); isText {
			s, _ := text.(string)
			out.Parts = append(out.Parts, A2APart{Kind: "text", Text: s})
			continue
		}
		out.Parts = append(out.Parts, A2APart{Kind: "other"})
	}
	out.PartCount = len(list)
	out.ContextID, out.TaskID = a2aText(msg, "contextId"), a2aText(msg, "taskId")
	if md, ok := a2aObject(o, "metadata"); ok {
		out.Metadata, _ = A2AStruct(md).(A2AJSON)
	}
	if cfg, ok := a2aObject(o, "configuration"); ok {
		if push, ok := a2aObject(cfg, "taskPushNotificationConfig"); ok {
			p := a2aPush(push)
			out.Push = &p
		}
	}
	return out, nil
}

func a2aRole(v any) (int, *A2ARPCError) {
	switch x := v.(type) {
	case nil:
		return 0, nil
	case string:
		switch x {
		case "ROLE_UNSPECIFIED":
			return 0, nil
		case "ROLE_USER":
			return 1, nil
		case "ROLE_AGENT":
			return 2, nil
		}
		return 0, a2aInvalidField("role", fmt.Sprintf("Invalid enum value %s for enum type lf.a2a.v1.Role", x))
	case json.Number:
		n, err := strconv.Atoi(string(x))
		if err == nil && n >= 0 && n <= 2 {
			return n, nil
		}
	}
	return 0, a2aInvalidField("role", fmt.Sprintf("Invalid enum value %s for enum type lf.a2a.v1.Role", a2aPyStr(v)))
}

// Page limits of ListTasks.
const (
	A2ADefaultPageSize = 50
	A2AMaxPageSize     = 100
)

var a2aPageOffset = regexp.MustCompile(`^[0-9]{1,18}$`)

// A2AListRequest is a ListTasksRequest.
type A2AListRequest struct {
	PageSize         int
	Offset           int
	IncludeArtifacts bool
}

// A2AListParams is ListTasksRequest checked as on_list_tasks checks it: no
// filters, a page size of 1 to 100, and a page token this server issued.
func A2AListParams(params any) (A2AListRequest, *A2ARPCError) {
	o := a2aParams(params)
	out := A2AListRequest{PageSize: A2ADefaultPageSize}
	if v, _ := a2aField(o, "contextId"); a2aTruthy(v) {
		return out, a2aListFilters()
	}
	if v, _ := a2aField(o, "status"); a2aTruthy(v) && v != "TASK_STATE_UNSPECIFIED" {
		return out, a2aListFilters()
	}
	if v, _ := a2aField(o, "statusTimestampAfter"); v != nil {
		return out, a2aListFilters()
	}
	if v, _ := a2aField(o, "pageSize"); v != nil {
		n, err := a2aInt32(v)
		if err != nil {
			return out, a2aInvalidField("pageSize", err.Error())
		}
		if n < 1 {
			return out, A2AInvalidParams("minimum page size is 1")
		}
		if n > A2AMaxPageSize {
			return out, A2AInvalidParams(fmt.Sprintf("maximum page size is %d", A2AMaxPageSize))
		}
		out.PageSize = n
	}
	if token := a2aText(o, "pageToken"); token != "" {
		offset, ok := A2ADecodePageToken(token)
		if !ok {
			return out, A2AInvalidParams("Invalid page token")
		}
		out.Offset = offset
	}
	if v, _ := a2aField(o, "includeArtifacts"); v == true {
		out.IncludeArtifacts = true
	}
	return out, nil
}

func a2aListFilters() *A2ARPCError {
	return A2AUnsupportedOperation("ListTasks filters (contextId, status, statusTimestampAfter) are not supported")
}

func a2aInt32(v any) (int, error) {
	switch x := v.(type) {
	case json.Number:
		if n, err := strconv.ParseInt(string(x), 10, 32); err == nil {
			return int(n), nil
		}
		if f, err := x.Float64(); err == nil && f == float64(int32(f)) {
			return int(f), nil
		}
	case float64:
		if x == float64(int32(x)) {
			return int(x), nil
		}
	case string:
		if n, err := strconv.ParseInt(x, 10, 32); err == nil {
			return int(n), nil
		}
	}
	return 0, fmt.Errorf("invalid value %s for int32", a2aPyRepr(v))
}

// A2AEncodePageToken is encode_page_token of an offset.
func A2AEncodePageToken(offset int) string {
	return base64.StdEncoding.EncodeToString([]byte(strconv.Itoa(offset)))
}

// A2ADecodePageToken is the offset a page token carries; false for a token
// that is not one this server issued or whose offset is past int32.
func A2ADecodePageToken(token string) (int, bool) {
	padded := token
	if m := len(padded) % 4; m != 0 {
		padded += "===="[:4-m]
	}
	raw, err := base64.StdEncoding.DecodeString(padded)
	if err != nil || !a2aPageOffset.Match(raw) {
		return 0, false
	}
	n, err := strconv.Atoi(string(raw))
	return n, err == nil && n <= math.MaxInt32
}

// A2APushConfigsKey is the task parameter that holds the push configs.
const A2APushConfigsKey = "a2a_push_configs"

// A2APushTokenSecret is the secret name of a push config's callback token.
func A2APushTokenSecret(taskID, configID string) string {
	return "a2a_push_token:" + taskID + ":" + configID
}

// A2AStoredPushConfigs is list_push_configs: the stored configs of a task's
// parameters (a non-list value is none).
func A2AStoredPushConfigs(params A2AJSON) []A2AJSON {
	v, _ := params.Get(A2APushConfigsKey)
	list, _ := v.([]any)
	var out []A2AJSON
	for _, e := range list {
		if c, ok := e.(A2AJSON); ok {
			out = append(out, c)
		}
	}
	return out
}

func a2aConfigID(c A2AJSON) string {
	v, _ := c.Get("id")
	return a2aPyStr(v)
}

// A2AUpsertPushConfig is upsert_push_config: the parameters with the config
// stored under id (replacing one with that id), and the stored config.
func A2AUpsertPushConfig(params A2AJSON, url, id string) (A2AJSON, A2AJSON) {
	stored := A2AJSON{{Key: "id", Value: id}, {Key: "url", Value: url}}
	out := append(A2AJSON{}, params...)
	configs := []any{}
	for _, c := range A2AStoredPushConfigs(params) {
		if a2aConfigID(c) != id {
			configs = append(configs, c)
		}
	}
	configs = append(configs, stored)
	out.Set(A2APushConfigsKey, configs)
	return out, stored
}

// A2AFindPushConfig is get_push_config.
func A2AFindPushConfig(params A2AJSON, id string) (A2AJSON, bool) {
	for _, c := range A2AStoredPushConfigs(params) {
		if a2aConfigID(c) == id {
			return c, true
		}
	}
	return nil, false
}

// A2ADeletePushConfig is delete_push_config: the parameters without the
// config, and whether it was there.
func A2ADeletePushConfig(params A2AJSON, id string) (A2AJSON, bool) {
	out := append(A2AJSON{}, params...)
	configs := []any{}
	all := A2AStoredPushConfigs(params)
	for _, c := range all {
		if a2aConfigID(c) != id {
			configs = append(configs, c)
		}
	}
	out.Set(A2APushConfigsKey, configs)
	return out, len(configs) != len(all)
}

// A2APushResult is task_push_config_result rendered by MessageToDict: the token is never returned.
func A2APushResult(taskID string, c A2AJSON) A2AJSON {
	id, _ := c.Get("id")
	url, _ := c.Get("url")
	return A2AJSON{{Key: "id", Value: a2aPyStr(id)}, {Key: "taskId", Value: taskID}, {Key: "url", Value: a2aPyStr(url)}}
}
