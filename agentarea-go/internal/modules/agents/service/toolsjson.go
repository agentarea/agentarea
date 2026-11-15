package service

import (
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

func strList(v *[]string) any {
	if v == nil {
		return nil
	}
	out := make([]any, len(*v))
	for i, s := range *v {
		out[i] = s
	}
	return out
}

func permissions(v *[]domain.MCPPermission, omitNil bool) any {
	if v == nil {
		return nil
	}
	out := make([]any, len(*v))
	for i, p := range *v {
		o := wirejson.Object{{Key: "tool_name", Value: p.ToolName}}
		if p.RequiresUserConfirmation != nil || !omitNil {
			o = append(o, wirejson.Member{Key: "requires_user_confirmation", Value: boolOrNil(p.RequiresUserConfirmation)})
		}
		out[i] = o
	}
	return out
}

func boolOrNil(b *bool) any {
	if b == nil {
		return nil
	}
	return *b
}

func strOrNil(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

// settingsObject is the settings in pydantic's field order (base class
// first). omitNil is exclude_none: the stored form leaves a nil field out.
func settingsObject(t domain.Tool, omitNil bool) wirejson.Object {
	s := t.Settings
	var o wirejson.Object
	add := func(key string, v any, isNil bool) {
		if isNil && omitNil {
			return
		}
		o = append(o, wirejson.Member{Key: key, Value: v})
	}
	add("requires_user_confirmation", boolOrNil(s.RequiresUserConfirmation), s.RequiresUserConfirmation == nil)
	switch t.Type {
	case domain.ToolCode:
		add("disabled_methods", strList(s.DisabledMethods), s.DisabledMethods == nil)
		add("image_model_id", strOrNil(s.ImageModelID), s.ImageModelID == nil)
		add("video_model_id", strOrNil(s.VideoModelID), s.VideoModelID == nil)
	case domain.ToolMCP:
		add("allowed_tools", permissions(s.MCPAllowed, omitNil), s.MCPAllowed == nil)
	case domain.ToolAgent:
		add("description_override", strOrNil(s.DescriptionOverride), s.DescriptionOverride == nil)
		add("agent_id", strOrNil(s.AgentID), s.AgentID == nil)
		add("a2a_url", strOrNil(s.A2AURL), s.A2AURL == nil)
		add("auth_secret_name", strOrNil(s.AuthSecretName), s.AuthSecretName == nil)
	case domain.ToolOpenAPI:
		add("openapi_connection_id", strOrNil(s.OpenAPIConnectionID), s.OpenAPIConnectionID == nil)
		add("allowed_tools", strList(s.OpenAPIAllowed), s.OpenAPIAllowed == nil)
		add("load_mode", strOrNil(s.LoadMode), s.LoadMode == nil)
	}
	if o == nil {
		o = wirejson.Object{}
	}
	return o
}

// Response is the tool as AgentResponse renders it: every field, null when unset.
func ToolResponse(t domain.Tool) wirejson.Object {
	o := wirejson.Object{{Key: "name", Value: t.Name}, {Key: "type", Value: t.Type}}
	if t.Settings == nil {
		return append(o, wirejson.Member{Key: "settings", Value: nil})
	}
	return append(o, wirejson.Member{Key: "settings", Value: settingsObject(t, false)})
}

// Stored is model_dump(exclude_none=True): what the tools column holds.
func ToolStored(t domain.Tool) wirejson.Object {
	o := wirejson.Object{{Key: "name", Value: t.Name}, {Key: "type", Value: t.Type}}
	if t.Settings == nil {
		return o
	}
	return append(o, wirejson.Member{Key: "settings", Value: settingsObject(t, true)})
}

type fieldErrs = []httpx.FieldError

func optString(o wirejson.Object, key string, loc []any, errs *fieldErrs) (*string, bool) {
	v, ok := o.Get(key)
	if !ok || v == nil {
		return nil, true
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.StringType(append(append([]any{}, loc...), key)...))
		return nil, false
	}
	return &s, true
}

func optBool(o wirejson.Object, key string, loc []any, errs *fieldErrs) *bool {
	v, ok := o.Get(key)
	if !ok || v == nil {
		return nil
	}
	b, isBool := v.(bool)
	if !isBool {
		*errs = append(*errs, httpx.BoolType(append(append([]any{}, loc...), key)...))
		return nil
	}
	return &b
}

func optStrList(o wirejson.Object, key string, loc []any, errs *fieldErrs) *[]string {
	v, ok := o.Get(key)
	if !ok || v == nil {
		return nil
	}
	arr, isArr := v.([]any)
	l := append(append([]any{}, loc...), key)
	if !isArr {
		*errs = append(*errs, httpx.ListType(l...))
		return nil
	}
	out := make([]string, 0, len(arr))
	for i, it := range arr {
		s, isStr := it.(string)
		if !isStr {
			*errs = append(*errs, httpx.StringType(append(append([]any{}, l...), i)...))
			continue
		}
		out = append(out, s)
	}
	return &out
}

// ParseTool is ToolConfig's validation of one raw entry at loc: the
// discriminator picks the variant, unknown settings keys are dropped, name is
// stripped and non-empty.
func ParseTool(v any, loc []any, errs *fieldErrs) (domain.Tool, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		*errs = append(*errs, httpx.FieldError{Type: "model_attributes_type", Loc: loc,
			Msg: "Input should be a valid dictionary or object to extract fields from"})
		return domain.Tool{}, false
	}
	tag, present := o.Get("type")
	tagStr, isStr := tag.(string)
	if !present || !isStr {
		*errs = append(*errs, httpx.FieldError{Type: "union_tag_not_found", Loc: loc,
			Msg: "Unable to extract tag using discriminator 'type'"})
		return domain.Tool{}, false
	}
	valid := false
	for _, t := range domain.ToolTypes() {
		valid = valid || t == tagStr
	}
	if !valid {
		*errs = append(*errs, httpx.FieldError{Type: "union_tag_invalid", Loc: loc,
			Msg: "Input tag '" + tagStr + "' found using 'type' does not match any of the expected tags: 'code', 'mcp', 'agent', 'openapi'"})
		return domain.Tool{}, false
	}
	loc = append(append([]any{}, loc...), tagStr)
	before := len(*errs)
	t := domain.Tool{Type: tagStr}
	nameLoc := append(append([]any{}, loc...), "name")
	nv, hasName := o.Get("name")
	switch name, isStr := nv.(string); {
	case !hasName:
		*errs = append(*errs, httpx.Missing(nameLoc...))
	case !isStr:
		*errs = append(*errs, httpx.StringType(nameLoc...))
	default:
		t.Name = strings.TrimFunc(name, isPySpace)
		if t.Name == "" {
			*errs = append(*errs, httpx.ValueError("Tool name cannot be empty", nameLoc...))
		}
	}
	sv, hasSettings := o.Get("settings")
	if hasSettings && sv != nil {
		so, isObj := sv.(wirejson.Object)
		sloc := append(append([]any{}, loc...), "settings")
		if !isObj {
			*errs = append(*errs, httpx.FieldError{Type: "model_attributes_type", Loc: sloc,
				Msg: "Input should be a valid dictionary or object to extract fields from"})
		} else {
			t.Settings = parseSettings(tagStr, so, sloc, errs)
		}
	}
	return t, len(*errs) == before
}

func isPySpace(r rune) bool {
	return r == ' ' || (r >= '\t' && r <= '\r') || (r >= 0x1c && r <= 0x1f) || r == 0x85 || r == 0xa0 ||
		r == 0x1680 || (r >= 0x2000 && r <= 0x200a) || r == 0x2028 || r == 0x2029 || r == 0x202f || r == 0x205f || r == 0x3000
}

func parseSettings(tag string, o wirejson.Object, loc []any, errs *fieldErrs) *domain.Settings {
	s := &domain.Settings{RequiresUserConfirmation: optBool(o, "requires_user_confirmation", loc, errs)}
	switch tag {
	case domain.ToolCode:
		s.DisabledMethods = optStrList(o, "disabled_methods", loc, errs)
		s.ImageModelID, _ = optString(o, "image_model_id", loc, errs)
		s.VideoModelID, _ = optString(o, "video_model_id", loc, errs)
	case domain.ToolMCP:
		s.MCPAllowed = parsePermissions(o, loc, errs)
	case domain.ToolAgent:
		s.DescriptionOverride, _ = optString(o, "description_override", loc, errs)
		s.AgentID, _ = optString(o, "agent_id", loc, errs)
		s.A2AURL, _ = optString(o, "a2a_url", loc, errs)
		s.AuthSecretName, _ = optString(o, "auth_secret_name", loc, errs)
	case domain.ToolOpenAPI:
		s.OpenAPIConnectionID, _ = optString(o, "openapi_connection_id", loc, errs)
		s.OpenAPIAllowed = optStrList(o, "allowed_tools", loc, errs)
		s.LoadMode, _ = optString(o, "load_mode", loc, errs)
		if s.LoadMode != nil && *s.LoadMode != "explicit" && *s.LoadMode != "searchable" {
			*errs = append(*errs, httpx.FieldError{Type: "literal_error", Loc: append(append([]any{}, loc...), "load_mode"),
				Msg: "Input should be 'explicit' or 'searchable'"})
		}
	}
	return s
}

func parsePermissions(o wirejson.Object, loc []any, errs *fieldErrs) *[]domain.MCPPermission {
	v, ok := o.Get("allowed_tools")
	if !ok || v == nil {
		return nil
	}
	l := append(append([]any{}, loc...), "allowed_tools")
	arr, isArr := v.([]any)
	if !isArr {
		*errs = append(*errs, httpx.ListType(l...))
		return nil
	}
	out := make([]domain.MCPPermission, 0, len(arr))
	for i, it := range arr {
		il := append(append([]any{}, l...), i)
		switch x := it.(type) {
		case string:
			out = append(out, domain.MCPPermission{ToolName: x})
		case wirejson.Object:
			name, hasName := x.Get("tool_name")
			ns, isStr := name.(string)
			switch {
			case !hasName:
				*errs = append(*errs, httpx.Missing(append(append([]any{}, il...), "tool_name")...))
			case !isStr:
				*errs = append(*errs, httpx.StringType(append(append([]any{}, il...), "tool_name")...))
			default:
				out = append(out, domain.MCPPermission{ToolName: ns, RequiresUserConfirmation: optBool(x, "requires_user_confirmation", il, errs)})
			}
		default:
			*errs = append(*errs, httpx.FieldError{Type: "model_attributes_type", Loc: il,
				Msg: "Input should be a valid dictionary or object to extract fields from"})
		}
	}
	return &out
}

// ParseStoredTools reads the tools column as AgentResponse.from_domain
// does: a list of objects, an entry that does not parse is skipped, a dict
// or a null is read as none.
func ParseStoredTools(raw []byte) (tools []domain.Tool, isList bool) {
	if len(raw) == 0 {
		return nil, false
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil, false
	}
	arr, ok := v.([]any)
	if !ok {
		return nil, false
	}
	for _, it := range arr {
		var errs fieldErrs
		if t, ok := ParseTool(it, nil, &errs); ok {
			tools = append(tools, t)
		}
	}
	return tools, true
}

// StoredJSON renders tools as the column holds them.
func StoredJSON(tools []domain.Tool) ([]byte, error) {
	arr := make([]any, len(tools))
	for i, t := range tools {
		arr[i] = ToolStored(t)
	}
	return wirejson.Marshal(arr, wirejson.Compact)
}
