package handlers

import (
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/openapispec"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// The OpenAPI write bodies (agentarea_openapi.schemas.dto), validated as
// pydantic does: every field's errors in one 422, extra keys refused.

var (
	oaHeaderName = regexp.MustCompile(`^[a-zA-Z0-9\-_]+$`)
	oaQueryName  = regexp.MustCompile(`^[A-Za-z0-9_.\-\[\]]+$`)
)

// oaFields walks an object's keys, refusing those not in allowed.
func oaFields(o wirejson.Object, allowed []string, loc []any, errs *[]httpx.FieldError) {
	for _, m := range o {
		ok := false
		for _, a := range allowed {
			if m.Key == a {
				ok = true
				break
			}
		}
		if !ok {
			*errs = append(*errs, httpx.ExtraForbidden(append(append([]any{}, loc...), m.Key)...))
		}
	}
}

func at(loc []any, more ...any) []any { return append(append([]any{}, loc...), more...) }

// oaStr reads a str field: ok false on an error; present false when absent;
// null is (nil, true, true) for nullable fields and an error otherwise.
func oaStr(o wirejson.Object, key string, loc []any, nullable bool, minLen, maxLen int, errs *[]httpx.FieldError) (s *string, present, ok bool) {
	v, has := o.Get(key)
	if !has {
		return nil, false, true
	}
	if v == nil && nullable {
		return nil, true, true
	}
	str, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.StringType(at(loc, key)...))
		return nil, true, false
	}
	n := utf8.RuneCountInString(str)
	if minLen > 0 && n < minLen {
		*errs = append(*errs, httpx.StringTooShort(minLen, at(loc, key)...))
		return nil, true, false
	}
	if maxLen > 0 && n > maxLen {
		*errs = append(*errs, httpx.StringTooLong(maxLen, at(loc, key)...))
		return nil, true, false
	}
	return &str, true, true
}

func oaUUID(o wirejson.Object, key string, loc []any, errs *[]httpx.FieldError) (*uuid.UUID, bool, bool) {
	v, has := o.Get(key)
	if !has {
		return nil, false, true
	}
	if v == nil {
		return nil, true, true
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, uuidType(at(loc, key)...))
		return nil, true, false
	}
	id, fe := httpx.ValidateUUID(s, at(loc, key)...)
	if fe != nil {
		*errs = append(*errs, *fe)
		return nil, true, false
	}
	u := uuid.MustParse(id)
	return &u, true, true
}

func oaDict(o wirejson.Object, key string, loc []any, errs *[]httpx.FieldError) (wirejson.Object, bool, bool) {
	v, has := o.Get(key)
	if !has {
		return nil, false, true
	}
	if v == nil {
		return nil, true, true
	}
	d, isObj := v.(wirejson.Object)
	if !isObj {
		*errs = append(*errs, httpx.DictType(at(loc, key)...))
		return nil, true, false
	}
	return d, true, true
}

// oaList reads a nullable list of objects; items is nil for null.
func oaList(o wirejson.Object, key string, loc []any, errs *[]httpx.FieldError) ([]any, bool, bool) {
	v, has := o.Get(key)
	if !has {
		return nil, false, true
	}
	if v == nil {
		return nil, true, true
	}
	l, isList := v.([]any)
	if !isList {
		*errs = append(*errs, httpx.ListType(at(loc, key)...))
		return nil, true, false
	}
	return l, true, true
}

func oaItem(v any, class string, loc []any, errs *[]httpx.FieldError) (wirejson.Object, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		*errs = append(*errs, modelType(class, loc...))
		return nil, false
	}
	return o, true
}

func oaHeaders(items []any, loc []any, errs *[]httpx.FieldError) ([]service.HeaderIn, bool) {
	out := []service.HeaderIn{}
	ok := true
	for i, it := range items {
		l := at(loc, i)
		o, isObj := oaItem(it, "HeaderInput", l, errs)
		if !isObj {
			ok = false
			continue
		}
		oaFields(o, []string{"name", "value"}, l, errs)
		name, present, nameOK := oaStr(o, "name", l, false, 0, 256, errs)
		if nameOK && !present {
			*errs = append(*errs, httpx.Missing(at(l, "name")...))
			nameOK = false
		}
		if nameOK && !oaHeaderName.MatchString(strings.TrimSpace(*name)) {
			*errs = append(*errs, httpx.ValueError("Header name contains invalid characters", at(l, "name")...))
			nameOK = false
		}
		value, _, valueOK := oaStr(o, "value", l, false, 0, 8192, errs)
		if valueOK && value != nil && strings.ContainsAny(*value, "\r\n\x00") {
			*errs = append(*errs, httpx.ValueError("Header value contains invalid characters", at(l, "value")...))
			valueOK = false
		}
		if !nameOK || !valueOK {
			ok = false
			continue
		}
		h := service.HeaderIn{Name: strings.TrimSpace(*name)}
		if value != nil {
			h.Value = *value
		}
		out = append(out, h)
	}
	return out, ok && len(*errs) == 0
}

func oaQuery(items []any, loc []any, errs *[]httpx.FieldError) ([]service.QueryIn, bool) {
	out := []service.QueryIn{}
	ok := true
	for i, it := range items {
		l := at(loc, i)
		o, isObj := oaItem(it, "QueryParamInput", l, errs)
		if !isObj {
			ok = false
			continue
		}
		oaFields(o, []string{"name", "secret", "value"}, l, errs)
		name, present, nameOK := oaStr(o, "name", l, false, 1, 256, errs)
		if nameOK && !present {
			*errs = append(*errs, httpx.Missing(at(l, "name")...))
			nameOK = false
		}
		if nameOK && !oaQueryName.MatchString(*name) {
			*errs = append(*errs, httpx.ValueError("Query parameter name contains invalid characters", at(l, "name")...))
			nameOK = false
		}
		secret := true
		secretOK := true
		if v, has := o.Get("secret"); has {
			b, isBool := v.(bool)
			if !isBool {
				*errs = append(*errs, httpx.BoolType(at(l, "secret")...))
				secretOK = false
			}
			secret = b
		}
		value, _, valueOK := oaStr(o, "value", l, false, 0, 8192, errs)
		if !nameOK || !secretOK || !valueOK {
			ok = false
			continue
		}
		q := service.QueryIn{Name: *name, Secret: secret}
		if value != nil {
			q.Value = *value
		}
		out = append(out, q)
	}
	if ok {
		seen := map[string]bool{}
		for _, q := range out {
			if seen[q.Name] {
				*errs = append(*errs, httpx.ValueError("Query parameter names must be unique.", loc...))
				return nil, false
			}
			seen[q.Name] = true
		}
	}
	return out, ok
}

func oaVars(items []any, loc []any, errs *[]httpx.FieldError) ([]service.VarIn, bool) {
	out := []service.VarIn{}
	ok := true
	for i, it := range items {
		l := at(loc, i)
		o, isObj := oaItem(it, "UrlVariableInput", l, errs)
		if !isObj {
			ok = false
			continue
		}
		oaFields(o, []string{"name", "value"}, l, errs)
		name, present, nameOK := oaStr(o, "name", l, false, 0, 128, errs)
		if nameOK && !present {
			*errs = append(*errs, httpx.Missing(at(l, "name")...))
			nameOK = false
		}
		if nameOK && !openapispec.VariableName.MatchString(*name) {
			*errs = append(*errs, httpx.ValueError("URL variable name must match [A-Za-z_][A-Za-z0-9_]*", at(l, "name")...))
			nameOK = false
		}
		value, present, valueOK := oaStr(o, "value", l, false, 1, 8192, errs)
		if valueOK && !present {
			*errs = append(*errs, httpx.Missing(at(l, "value")...))
			valueOK = false
		}
		if !nameOK || !valueOK {
			ok = false
			continue
		}
		out = append(out, service.VarIn{Name: *name, Value: *value})
	}
	return out, ok
}

// oaBaseURL is _validate_base_url_field's syntax half: placeholders in the
// path only. The address check is the service's (400).
func oaBaseURL(s string, loc []any, errs *[]httpx.FieldError) bool {
	if _, err := openapispec.TemplateVariables(s); err != nil {
		*errs = append(*errs, httpx.ValueError(err.Error(), loc...))
		return false
	}
	return true
}

func createFields() []string {
	return []string{"name", "base_url", "description", "spec_url", "spec_content", "auth_config_id",
		"custom_headers", "custom_query_params", "url_variables"}
}

// connectionCreateBody is OpenAPIConnectionCreate.
func connectionCreateBody(v any, errs *[]httpx.FieldError) (service.ConnectionCreate, bool) {
	o, ok := model(v, errs)
	if !ok {
		return service.ConnectionCreate{}, false
	}
	loc := []any{"body"}
	n := len(*errs)
	oaFields(o, createFields(), loc, errs)
	var in service.ConnectionCreate
	if name, present, ok := oaStr(o, "name", loc, false, 1, 255, errs); ok {
		if !present {
			*errs = append(*errs, httpx.Missing("body", "name"))
		} else {
			in.Name = *name
		}
	}
	if base, present, ok := oaStr(o, "base_url", loc, false, 0, 500, errs); ok {
		if !present {
			*errs = append(*errs, httpx.Missing("body", "base_url"))
		} else if oaBaseURL(*base, at(loc, "base_url"), errs) {
			in.BaseURL = *base
		}
	}
	in.Description, _, _ = oaStr(o, "description", loc, true, 0, 0, errs)
	in.SpecURL, _, _ = oaStr(o, "spec_url", loc, true, 0, 0, errs)
	if spec, _, ok := oaDict(o, "spec_content", loc, errs); ok && spec != nil {
		in.SpecContent = spec
	}
	in.AuthConfigID, _, _ = oaUUID(o, "auth_config_id", loc, errs)
	if items, _, ok := oaList(o, "custom_headers", loc, errs); ok && items != nil {
		in.Headers, _ = oaHeaders(items, at(loc, "custom_headers"), errs)
	}
	if items, _, ok := oaList(o, "custom_query_params", loc, errs); ok && items != nil {
		in.Query, _ = oaQuery(items, at(loc, "custom_query_params"), errs)
	}
	if items, _, ok := oaList(o, "url_variables", loc, errs); ok && items != nil {
		in.URLVariables, _ = oaVars(items, at(loc, "url_variables"), errs)
	}
	return in, len(*errs) == n
}

// connectionPatchBody is OpenAPIConnectionUpdate. A null name or base_url
// is refused here: the columns are NOT NULL, which Python reported as a 500.
func connectionPatchBody(v any, errs *[]httpx.FieldError) (service.ConnectionPatch, bool) {
	o, ok := model(v, errs)
	if !ok {
		return service.ConnectionPatch{}, false
	}
	loc := []any{"body"}
	n := len(*errs)
	oaFields(o, append(createFields(), "cost"), loc, errs)
	var p service.ConnectionPatch
	if name, present, ok := oaStr(o, "name", loc, false, 1, 255, errs); ok && present {
		p.NameSet, p.Name = true, *name
	}
	if base, present, ok := oaStr(o, "base_url", loc, false, 0, 500, errs); ok && present && oaBaseURL(*base, at(loc, "base_url"), errs) {
		p.BaseURLSet, p.BaseURL = true, *base
	}
	if d, present, ok := oaStr(o, "description", loc, true, 0, 0, errs); ok && present {
		p.DescriptionSet, p.Description = true, d
	}
	if u, present, ok := oaStr(o, "spec_url", loc, true, 0, 0, errs); ok && present {
		p.SpecURLSet, p.SpecURL = true, u
	}
	if spec, present, ok := oaDict(o, "spec_content", loc, errs); ok && present {
		p.SpecContentSet = true
		if spec != nil {
			p.SpecContent = spec
		}
	}
	if id, present, ok := oaUUID(o, "auth_config_id", loc, errs); ok && present {
		p.AuthConfigSet, p.AuthConfigID = true, id
	}
	if items, _, ok := oaList(o, "custom_headers", loc, errs); ok && items != nil {
		p.Headers, p.HeadersSet = oaHeaders(items, at(loc, "custom_headers"), errs)
	}
	if items, _, ok := oaList(o, "custom_query_params", loc, errs); ok && items != nil {
		p.Query, p.QuerySet = oaQuery(items, at(loc, "custom_query_params"), errs)
	}
	if items, _, ok := oaList(o, "url_variables", loc, errs); ok && items != nil {
		p.URLVariables, p.URLVariablesSet = oaVars(items, at(loc, "url_variables"), errs)
	}
	if cost, present, ok := oaDict(o, "cost", loc, errs); ok && present {
		if cost != nil {
			if err := openapispec.CheckConnectionCost(cost); err != nil {
				*errs = append(*errs, httpx.ValueError(err.Error(), at(loc, "cost")...))
			} else {
				p.CostSet, p.Cost = true, plainMap(cost)
			}
		} else {
			p.CostSet = true
		}
	}
	return p, len(*errs) == n
}

func plainMap(o wirejson.Object) map[string]any {
	m, _ := openapispec.Plain(o).(map[string]any)
	return m
}

// previewBody is SpecPreviewRequest (extra keys ignored).
func previewBody(v any, errs *[]httpx.FieldError) (*string, any, bool) {
	o, ok := model(v, errs)
	if !ok {
		return nil, nil, false
	}
	n := len(*errs)
	u, _, _ := oaStr(o, "spec_url", []any{"body"}, true, 0, 0, errs)
	var spec any
	if d, _, ok := oaDict(o, "spec_content", []any{"body"}, errs); ok && d != nil {
		spec = d
	}
	return u, spec, len(*errs) == n
}

// oaSharingBody is ConnectionSharingRequest.
func oaSharingBody(v any, errs *[]httpx.FieldError) (bool, bool) {
	o, ok := model(v, errs)
	if !ok {
		return false, false
	}
	raw, has := o.Get("shared")
	if !has {
		*errs = append(*errs, httpx.Missing("body", "shared"))
		return false, false
	}
	b, isBool := raw.(bool)
	if !isBool {
		*errs = append(*errs, httpx.BoolType("body", "shared"))
		return false, false
	}
	return b, true
}

// catalogConnectBody is CatalogConnectRequest: 1 to 16 {name, value}.
func catalogConnectBody(v any, errs *[]httpx.FieldError) ([][2]string, bool) {
	o, ok := model(v, errs)
	if !ok {
		return nil, false
	}
	n := len(*errs)
	oaFields(o, []string{"credentials"}, []any{"body"}, errs)
	items, present, ok := oaList(o, "credentials", []any{"body"}, errs)
	switch {
	case !ok:
		return nil, false
	case !present:
		*errs = append(*errs, httpx.Missing("body", "credentials"))
		return nil, false
	case items == nil:
		*errs = append(*errs, httpx.ListType("body", "credentials"))
		return nil, false
	case len(items) < 1:
		*errs = append(*errs, listTooShort(1, len(items), "body", "credentials"))
		return nil, false
	case len(items) > 16:
		*errs = append(*errs, listTooLong(16, len(items), "body", "credentials"))
		return nil, false
	}
	var out [][2]string
	for i, it := range items {
		l := []any{"body", "credentials", i}
		o, isObj := oaItem(it, "CatalogKeyValue", l, errs)
		if !isObj {
			continue
		}
		oaFields(o, []string{"name", "value"}, l, errs)
		name, np, nok := oaStr(o, "name", l, false, 0, 256, errs)
		if nok && !np {
			*errs = append(*errs, httpx.Missing(at(l, "name")...))
			nok = false
		}
		value, vp, vok := oaStr(o, "value", l, false, 0, 8192, errs)
		if vok && !vp {
			*errs = append(*errs, httpx.Missing(at(l, "value")...))
			vok = false
		}
		if nok && vok {
			out = append(out, [2]string{*name, *value})
		}
	}
	return out, len(*errs) == n
}

func uuidType(loc ...any) httpx.FieldError {
	return httpx.FieldError{Type: "uuid_type", Loc: loc, Msg: "UUID input should be a string, bytes or UUID object"}
}

func listTooShort(min, actual int, loc ...any) httpx.FieldError {
	return httpx.FieldError{Type: "too_short", Loc: loc,
		Msg: fmt.Sprintf("List should have at least %d item after validation, not %d", min, actual),
		Ctx: wirejson.Object{{Key: "field_type", Value: "List"}, {Key: "min_length", Value: min}, {Key: "actual_length", Value: actual}}}
}

func listTooLong(max, actual int, loc ...any) httpx.FieldError {
	return httpx.FieldError{Type: "too_long", Loc: loc,
		Msg: fmt.Sprintf("List should have at most %d items after validation, not %d", max, actual),
		Ctx: wirejson.Object{{Key: "field_type", Value: "List"}, {Key: "max_length", Value: max}, {Key: "actual_length", Value: actual}}}
}

func modelType(class string, loc ...any) httpx.FieldError {
	return httpx.FieldError{Type: "model_type", Loc: loc,
		Msg: "Input should be a valid dictionary or instance of " + class,
		Ctx: wirejson.Object{{Key: "class_name", Value: class}}}
}
