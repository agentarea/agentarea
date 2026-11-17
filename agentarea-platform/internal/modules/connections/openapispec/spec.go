package openapispec

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

var errorPathRE = regexp.MustCompile(`^\$(?:\.[A-Za-z_][A-Za-z0-9_\-]*|\[\d+\])+$`)

// Parameter is one parameter of an operation, its location as the spec wrote it.
type Parameter struct {
	Name string
	// In is the location; nil when the spec wrote null.
	In       any
	Required any
	Schema   any
}

// InPath, InQuery and InHeader read In.
func (p Parameter) InPath() bool   { return p.In == "path" }
func (p Parameter) InQuery() bool  { return p.In == "query" }
func (p Parameter) InHeader() bool { return p.In == "header" }

// RequestBody is an operation's body: its content type and schema.
type RequestBody struct {
	ContentType string
	Required    any
	Schema      any
}

// Operation is one record of parse_openapi_operations.
type Operation struct {
	Name        string
	Description string
	Method      string
	Path        string
	Parameters  []Parameter
	RequestBody *RequestBody
	InputSchema wirejson.Object
	// Cost is the operation's declaration, else the spec's default.
	Cost              any
	RequestTransform  []any
	ResponseTransform []any
	ErrorPath         string
}

// Tool is one available_tools entry: {name, description, inputSchema}.
type Tool struct {
	Name        string
	Description string
	InputSchema wirejson.Object
}

// Info is openapi_spec_info.
type Info struct {
	Title, Description, Version, BaseURL *string
}

func httpMethods() []string {
	return []string{"get", "post", "put", "patch", "delete", "head", "options"}
}

// reservedTools are CONTROL_FLOW_TOOL_NAMES: a workflow built-in owns them.
func reservedTools() map[string]bool {
	return map[string]bool{
		"completion": true, "task_complete": true, "request_user_input": true, "recall_history": true,
		"read_tool_output": true, "activate_tool_source": true, "activate_skill": true, "load_tools": true, "wait": true,
	}
}

var invalidToolChars = regexp.MustCompile(`[^a-zA-Z0-9_-]`)

// Slugify is _slugify_name: characters invalid in a function name become underscores.
func Slugify(name string) string { return invalidToolChars.ReplaceAllString(name, "_") }

// ToolTarget is openapi_tool_target: the id-qualified name a policy rule allows an operation by.
func ToolTarget(connectionID, toolName string) string {
	return "openapi:" + connectionID + ":" + toolName
}

func expectObject(v any, where string) (wirejson.Object, error) {
	o, ok := asObject(v)
	if !ok {
		return nil, errorf("Invalid OpenAPI spec: %s must be an object", where)
	}
	return o, nil
}

func optionalStr(v any, where string) (string, error) {
	if v == nil {
		return "", nil
	}
	s, ok := v.(string)
	if !ok {
		return "", errorf("Invalid OpenAPI spec: %s must be a string", where)
	}
	return s, nil
}

func schemaOf(v any, where string) (any, error) {
	if _, ok := v.(bool); ok {
		return v, nil
	}
	if isObject(v) {
		return v, nil
	}
	return nil, errorf("Invalid OpenAPI spec: %s must be a schema object", where)
}

// resolveRef is _resolve_ref: a local $ref followed, cycles broken with {}.
func resolveRef(v any, spec wirejson.Object, seen map[string]bool) any {
	o, ok := asObject(v)
	if !ok {
		return v
	}
	raw, ok := o.Get("$ref")
	if !ok {
		return v
	}
	ref, ok := raw.(string)
	if !ok || !strings.HasPrefix(ref, "#/") {
		return v
	}
	if seen == nil {
		seen = map[string]bool{}
	}
	if seen[ref] {
		return wirejson.Object{}
	}
	seen[ref] = true
	var resolved any = spec
	for _, part := range strings.Split(strings.TrimLeft(ref, "#/"), "/") {
		part = strings.ReplaceAll(strings.ReplaceAll(part, "~1", "/"), "~0", "~")
		node, isObj := asObject(resolved)
		if !isObj {
			return v
		}
		resolved = get(node, part, nil)
		if resolved == nil {
			return v
		}
	}
	if ro, ok := asObject(resolved); ok && has(ro, "$ref") {
		return resolveRef(ro, spec, seen)
	}
	return resolved
}

func parameters(container wirejson.Object, spec wirejson.Object, where string) ([]wirejson.Object, error) {
	raw := or(get(container, "parameters", nil), []any{})
	list, ok := raw.([]any)
	if !ok {
		return nil, errorf("Invalid OpenAPI spec: %s.parameters must be a list", where)
	}
	out := make([]wirejson.Object, 0, len(list))
	for i, item := range list {
		at := fmt.Sprintf("%s.parameters[%d]", where, i)
		p, err := expectObject(resolveRef(item, spec, nil), at)
		if err != nil {
			return nil, err
		}
		if _, err := optionalStr(get(p, "name", nil), at+".name"); err != nil {
			return nil, err
		}
		if _, err := optionalStr(get(p, "in", nil), at+".in"); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, nil
}

func paramSchema(p wirejson.Object, spec wirejson.Object, where string) (any, error) {
	raw := get(p, "schema", wirejson.Object{{Key: "type", Value: "string"}})
	return schemaOf(resolveRef(raw, spec, nil), where+" schema")
}

func requestBody(op wirejson.Object, spec wirejson.Object, where string) (wirejson.Object, wirejson.Object, error) {
	raw := get(op, "requestBody", nil)
	if !truthy(raw) {
		return nil, nil, nil
	}
	body, err := expectObject(resolveRef(raw, spec, nil), where+".requestBody")
	if err != nil {
		return nil, nil, err
	}
	content, err := expectObject(or(get(body, "content", nil), wirejson.Object{}), where+".requestBody.content")
	if err != nil {
		return nil, nil, err
	}
	return body, content, nil
}

func mediaSchema(content wirejson.Object, ct string, spec wirejson.Object, where string) (any, error) {
	at := fmt.Sprintf("%s.requestBody.content[%s]", where, pyStr(ct))
	media, err := expectObject(get(content, ct, nil), at)
	if err != nil {
		return nil, err
	}
	return schemaOf(resolveRef(get(media, "schema", wirejson.Object{}), spec, nil), at+".schema")
}

func generateName(method, path string) string {
	cleaned := strings.NewReplacer("{", "", "}", "").Replace(path)
	var segs []string
	for _, s := range strings.Split(cleaned, "/") {
		if s != "" {
			segs = append(segs, s)
		}
	}
	return method + "_" + strings.Join(segs, "_")
}

// paramKey is (name, in) with "" for an absent key, as _merge_parameters keys them.
func paramKey(p wirejson.Object) string {
	return repr(get(p, "name", "")) + "\x00" + repr(get(p, "in", ""))
}

func mergeParameters(pathParams, opParams []wirejson.Object) []wirejson.Object {
	var order []string
	byKey := map[string]wirejson.Object{}
	for _, list := range [][]wirejson.Object{pathParams, opParams} {
		for _, p := range list {
			k := paramKey(p)
			if _, ok := byKey[k]; !ok {
				order = append(order, k)
			}
			byKey[k] = p
		}
	}
	out := make([]wirejson.Object, len(order))
	for i, k := range order {
		out[i] = byKey[k]
	}
	return out
}

func isConfigured(p wirejson.Object, configured map[string]bool) bool {
	name, _ := get(p, "name", nil).(string)
	return get(p, "in", "query") == "query" && configured[name]
}

func paramName(p wirejson.Object) string {
	s, _ := get(p, "name", "").(string)
	return s
}

func buildInputSchema(op wirejson.Object, pathParams []wirejson.Object, spec wirejson.Object, configured map[string]bool, where string) (wirejson.Object, error) {
	props := wirejson.Object{}
	required := []any{}
	opParams, err := parameters(op, spec, where)
	if err != nil {
		return nil, err
	}
	for _, p := range mergeParameters(pathParams, opParams) {
		if isConfigured(p, configured) {
			continue
		}
		name := paramName(p)
		if name == "" {
			continue
		}
		schema, err := paramSchema(p, spec, fmt.Sprintf("%s parameter %s", where, pyStr(name)))
		if err != nil {
			return nil, err
		}
		props.Set(name, schema)
		if truthy(get(p, "required", false)) {
			required = append(required, name)
		}
	}
	body, content, err := requestBody(op, spec, where)
	if err != nil {
		return nil, err
	}
	if body != nil && has(content, "application/json") {
		schema, err := mediaSchema(content, "application/json", spec, where)
		if err != nil {
			return nil, err
		}
		if truthy(schema) {
			props.Set("body", schema)
			if truthy(get(body, "required", true)) {
				required = append(required, "body")
			}
		}
	}
	return wirejson.Object{
		{Key: "type", Value: "object"},
		{Key: "properties", Value: props},
		{Key: "required", Value: required},
	}, nil
}

func errorPath(node wirejson.Object, where string) (string, error) {
	raw := get(node, "x-agentarea-error-path", nil)
	if raw == nil {
		return "", nil
	}
	s, ok := raw.(string)
	if !ok || !errorPathRE.MatchString(s) {
		return "", errorf("%s.x-agentarea-error-path must be a path like $.field, got %s", where, repr(raw))
	}
	return s, nil
}

// ParseOperations is parse_openapi_operations: every operation of an
// OpenAPI 3.x document, query parameters named in configured left out (the
// connection sends its own value). A malformed document is an *Error.
func ParseOperations(doc any, configured map[string]bool) ([]Operation, error) {
	spec, ok := asObject(doc)
	if !ok {
		return nil, errorf("An OpenAPI spec must be an object")
	}
	if has(spec, "swagger") {
		return nil, errorf("Swagger 2.0 specs are not supported. Please convert to OpenAPI 3.x.")
	}
	version := get(spec, "openapi", "")
	if s, isStr := version.(string); !isStr || !strings.HasPrefix(s, "3.") {
		return nil, errorf("Only OpenAPI 3.x specs are supported, got: %s", repr(version))
	}
	paths, err := expectObject(or(get(spec, "paths", nil), wirejson.Object{}), "paths")
	if err != nil {
		return nil, err
	}
	if err := CheckPayers(get(spec, "x-agentarea-payers", nil)); err != nil {
		return nil, err
	}
	defaultCost := get(spec, "x-agentarea-cost", nil)
	if _, err := CostSource(defaultCost); err != nil {
		return nil, err
	}
	defaultErrorPath, err := errorPath(spec, "spec")
	if err != nil {
		return nil, err
	}
	var ops []Operation
	for _, pm := range paths {
		path := pm.Key
		item, isObj := asObject(pm.Value)
		if !truthy(pm.Value) || !isObj {
			continue
		}
		where := fmt.Sprintf("paths[%s]", pyStr(path))
		pathParams, err := parameters(item, spec, where)
		if err != nil {
			return nil, err
		}
		for _, method := range httpMethods() {
			if !has(item, method) {
				continue
			}
			opWhere := where + "." + method
			op, err := expectObject(get(item, method, nil), opWhere)
			if err != nil {
				return nil, err
			}
			opID, err := optionalStr(get(op, "operationId", nil), opWhere+".operationId")
			if err != nil {
				return nil, err
			}
			summary, err := optionalStr(get(op, "summary", nil), opWhere+".summary")
			if err != nil {
				return nil, err
			}
			details, err := optionalStr(get(op, "description", nil), opWhere+".description")
			if err != nil {
				return nil, err
			}
			name := opID
			if name == "" {
				name = generateName(method, path)
			}
			description := summary
			if description == "" {
				description = details
			}
			opParams, err := parameters(op, spec, opWhere)
			if err != nil {
				return nil, err
			}
			var params []Parameter
			for _, p := range mergeParameters(pathParams, opParams) {
				if isConfigured(p, configured) {
					continue
				}
				pname := paramName(p)
				if pname == "" {
					continue
				}
				schema, err := paramSchema(p, spec, fmt.Sprintf("%s parameter %s", opWhere, pyStr(pname)))
				if err != nil {
					return nil, err
				}
				params = append(params, Parameter{Name: pname, In: get(p, "in", "query"), Required: get(p, "required", false), Schema: schema})
			}
			var rb *RequestBody
			body, content, err := requestBody(op, spec, opWhere)
			if err != nil {
				return nil, err
			}
			if body != nil {
				ct := "application/json"
				var schema any
				if has(content, "application/json") {
					schema, err = mediaSchema(content, ct, spec, opWhere)
				} else if len(content) > 0 {
					ct = content[0].Key
					schema, err = mediaSchema(content, ct, spec, opWhere)
				}
				if err != nil {
					return nil, err
				}
				rb = &RequestBody{ContentType: ct, Required: get(body, "required", true), Schema: or(schema, wirejson.Object{})}
			}
			input, err := buildInputSchema(op, pathParams, spec, configured, opWhere)
			if err != nil {
				return nil, err
			}
			ownCost := get(op, "x-agentarea-cost", nil)
			if _, err := CostSource(ownCost); err != nil {
				return nil, err
			}
			respT := or(get(op, "x-agentarea-response-transform", nil), []any{})
			respList, ok := respT.([]any)
			if !ok {
				return nil, errorf("%s.x-agentarea-response-transform must be a list", opWhere)
			}
			reqT := or(get(op, "x-agentarea-request-transform", nil), []any{})
			if err := CheckRequestTransform(reqT); err != nil {
				return nil, errorf("%s: %s", opWhere, err.Error())
			}
			reqList, _ := reqT.([]any)
			ep, err := errorPath(op, opWhere)
			if err != nil {
				return nil, err
			}
			if ep == "" {
				ep = defaultErrorPath
			}
			cost := ownCost
			if cost == nil {
				cost = defaultCost
			}
			ops = append(ops, Operation{
				Name: name, Description: description, Method: strings.ToUpper(method), Path: path,
				Parameters: params, RequestBody: rb, InputSchema: input, Cost: cost,
				RequestTransform: reqList, ResponseTransform: respList, ErrorPath: ep,
			})
		}
	}
	return ops, nil
}

// ParseSpec is parse_openapi_spec: the {name, description, inputSchema}
// tools of a document, which must also have a well-formed info and servers
// and no operation named after a workflow built-in.
func ParseSpec(doc any, configured map[string]bool) ([]Tool, error) {
	ops, err := ParseOperations(doc, configured)
	if err != nil {
		return nil, err
	}
	if _, err := SpecInfo(doc); err != nil {
		return nil, err
	}
	out := make([]Tool, 0, len(ops))
	for _, op := range ops {
		if reservedTools()[Slugify(op.Name)] {
			return nil, errorf("Operation %s (%s %s) uses a tool name reserved for a workflow built-in; give it a different operationId",
				pyStr(op.Name), op.Method, op.Path)
		}
		out = append(out, Tool{Name: op.Name, Description: op.Description, InputSchema: op.InputSchema})
	}
	return out, nil
}

func infoText(v any, where string) (*string, error) {
	var n string
	switch t := v.(type) {
	case json.Number:
		n = t.String()
	case wirejson.Float:
		n = wirejson.FormatFloat(float64(t))
	case float64:
		n = wirejson.FormatFloat(t)
	default:
		s, err := optionalStr(v, where)
		if err != nil || v == nil {
			return nil, err
		}
		return &s, nil
	}
	return &n, nil
}

// SpecInfo is openapi_spec_info: title, description, version and the first server's url.
func SpecInfo(doc any) (Info, error) {
	spec, ok := asObject(doc)
	if !ok {
		return Info{}, errorf("An OpenAPI spec must be an object")
	}
	info, err := expectObject(or(get(spec, "info", nil), wirejson.Object{}), "info")
	if err != nil {
		return Info{}, err
	}
	servers, ok := or(get(spec, "servers", nil), []any{}).([]any)
	if !ok {
		return Info{}, errorf("Invalid OpenAPI spec: servers must be a list")
	}
	var urls []*string
	for i, s := range servers {
		at := fmt.Sprintf("servers[%d]", i)
		so, err := expectObject(s, at)
		if err != nil {
			return Info{}, err
		}
		raw := get(so, "url", nil)
		u, err := optionalStr(raw, at+".url")
		if err != nil {
			return Info{}, err
		}
		if raw == nil {
			urls = append(urls, nil)
		} else {
			urls = append(urls, &u)
		}
	}
	var out Info
	if out.Title, err = infoText(get(info, "title", nil), "info.title"); err != nil {
		return Info{}, err
	}
	if out.Description, err = infoText(get(info, "description", nil), "info.description"); err != nil {
		return Info{}, err
	}
	if out.Version, err = infoText(get(info, "version", nil), "info.version"); err != nil {
		return Info{}, err
	}
	if len(urls) > 0 {
		out.BaseURL = urls[0]
	}
	return out, nil
}
