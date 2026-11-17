package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

// input is what a route's parameters and body validated to.
type input struct {
	ids         map[string]uuid.UUID
	specID      *uuid.UUID
	configID    *uuid.UUID
	modelSpecID *uuid.UUID
	isActive    *bool
	kind        *string
	newConfig   domain.NewConfig
	patch       domain.ConfigPatch
	newInstance domain.NewInstance
	bulk        []domain.NewInstance
	providerKey string
	apiKey      *string
	endpointURL *string
	testConfig  uuid.UUID
	testSpec    uuid.UUID
	testMessage *string
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

type request struct {
	pathUUIDs []string
	query     func(q url.Values, in *input, errs *[]httpx.FieldError) url.Values
	body      func(v any, in *input, errs *[]httpx.FieldError) any
}

func (rq request) middleware(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			var fes []httpx.FieldError
			in := input{ids: map[string]uuid.UUID{}}
			for _, name := range rq.pathUUIDs {
				id, fe := httpx.ValidateUUID(chi.URLParam(r, name), "path", name)
				if fe != nil {
					fes = append(fes, *fe)
					continue
				}
				in.ids[name] = uuid.MustParse(id)
			}
			if rq.query != nil {
				q := rq.query(r.URL.Query(), &in, &fes)
				r.URL.RawQuery = q.Encode()
			}
			var canonical any
			if rq.body != nil {
				v, err := readBody(r)
				if err != nil {
					errs.Write(w, r, err)
					return
				}
				canonical = rq.body(v, &in, &fes)
			}
			if err := httpx.Validation(fes...); err != nil {
				errs.Write(w, r, err)
				return
			}
			if rq.body != nil {
				raw, err := json.Marshal(canonical)
				if err != nil {
					errs.Write(w, r, err)
					return
				}
				r.Body = io.NopCloser(bytes.NewReader(raw))
				r.ContentLength = int64(len(raw))
				r.Header.Set("Content-Type", "application/json")
			}
			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), inputKey{}, in)))
		})
	}
}

func last(q url.Values, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

func queryUUID(q url.Values, key string, out url.Values, errs *[]httpx.FieldError) *uuid.UUID {
	v, ok := last(q, key)
	if !ok {
		return nil
	}
	id, fe := httpx.ValidateUUID(v, "query", key)
	if fe != nil {
		*errs = append(*errs, *fe)
		return nil
	}
	u := uuid.MustParse(id)
	out.Set(key, id)
	return &u
}

func queryBool(q url.Values, key string, out url.Values, errs *[]httpx.FieldError) *bool {
	v, ok := last(q, key)
	if !ok {
		return nil
	}
	b, ok := httpx.ParseBool(v)
	if !ok {
		*errs = append(*errs, httpx.BoolParsing("query", key))
		return nil
	}
	out.Set(key, strconv.FormatBool(b))
	return &b
}

// Kinds are ModelKind's values.
func Kinds() []string { return []string{"chat", "embedding", "image", "video", "decision"} }

func configsQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	out := url.Values{}
	in.specID = queryUUID(q, "provider_spec_id", out, errs)
	in.isActive = queryBool(q, "is_active", out, errs)
	return out
}

func instancesQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	out := url.Values{}
	in.configID = queryUUID(q, "provider_config_id", out, errs)
	in.modelSpecID = queryUUID(q, "model_spec_id", out, errs)
	in.isActive = queryBool(q, "is_active", out, errs)
	if v, ok := last(q, "kind"); ok {
		valid := false
		for _, k := range Kinds() {
			if v == k {
				valid = true
			}
		}
		if valid {
			in.kind = &v
			out.Set("kind", v)
		} else {
			*errs = append(*errs, httpx.EnumError(Kinds(), "query", "kind"))
		}
	}
	return out
}

// MaxName and MaxDescription are the DTO's Field bounds (schemas/dto.py).
const (
	MaxName        = 255
	MaxDescription = 1000
	BulkMaxItems   = 500
)

// endpointURL is _checked_endpoint_url.
func endpointURL(v *string, errs *[]httpx.FieldError) {
	if v == nil || *v == "" {
		return
	}
	if msg := domain.CheckEndpointURL(*v); msg != "" {
		*errs = append(*errs, httpx.ValueError(msg, "body", "endpoint_url"))
	}
}

// apiKeyField is api_key with its before-validator: a string is stripped, "" is None.
func apiKeyField(o wirejson.Object, errs *[]httpx.FieldError) (value *string, set bool) {
	value, set = str(o, "api_key", 0, 0, true, errs)
	if value != nil {
		s := pyStrip(*value)
		if s == "" {
			return nil, set
		}
		value = &s
	}
	return value, set
}

const bothKeysDetail = "Provide either api_key or api_key_secret_id, not both: api_key stores a new secret, api_key_secret_id reuses an existing one."

func configFields() []string {
	return []string{"provider_spec_id", "name", "api_key", "api_key_secret_id", "endpoint_url", "description", "is_public", "is_active"}
}

// createConfigBody is ProviderConfigCreate (extra="forbid").
func createConfigBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	n0 := len(*errs)
	spec, set := uuidField(o, "provider_spec_id", errs)
	if !set {
		*errs = append(*errs, httpx.Missing("body", "provider_spec_id"))
	} else if spec == nil && len(*errs) == n0 {
		*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", "provider_spec_id"}, Msg: "UUID input should be a string, bytes or UUID object"})
	} else if spec != nil {
		in.newConfig.ProviderSpecID = *spec
	}
	name, set := str(o, "name", 1, MaxName, false, errs)
	switch {
	case !set:
		*errs = append(*errs, httpx.Missing("body", "name"))
	case name != nil:
		stripped := pyStrip(*name)
		if stripped == "" {
			*errs = append(*errs, httpx.ValueError("name cannot be empty or whitespace", "body", "name"))
		}
		in.newConfig.Name = stripped
	}
	in.newConfig.APIKey, _ = apiKeyField(o, errs)
	in.newConfig.APIKeySecretID, _ = uuidField(o, "api_key_secret_id", errs)
	in.newConfig.EndpointURL, _ = str(o, "endpoint_url", 0, 0, true, errs)
	endpointURL(in.newConfig.EndpointURL, errs)
	in.newConfig.Description, _ = str(o, "description", 0, MaxDescription, true, errs)
	if b, _ := boolField(o, "is_public", false, errs); b != nil {
		in.newConfig.IsPublic = *b
	}
	extraForbidden(o, configFields()[:7], errs)
	if len(*errs) == n0 && in.newConfig.APIKey != nil && in.newConfig.APIKeySecretID != nil {
		*errs = append(*errs, httpx.ValueError(bothKeysDetail, "body"))
	}
	return map[string]any{}
}

// updateConfigBody is ProviderConfigUpdate: only sent keys are applied.
func updateConfigBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	n0 := len(*errs)
	p := &in.patch
	p.Name.Value, p.Name.Set = str(o, "name", 1, MaxName, true, errs)
	p.APIKey.Value, p.APIKey.Set = apiKeyField(o, errs)
	p.APIKeySecretID.Value, p.APIKeySecretID.Set = uuidField(o, "api_key_secret_id", errs)
	p.EndpointURL.Value, p.EndpointURL.Set = str(o, "endpoint_url", 0, 0, true, errs)
	endpointURL(p.EndpointURL.Value, errs)
	p.Description.Value, p.Description.Set = str(o, "description", 0, MaxDescription, true, errs)
	p.IsActive.Value, p.IsActive.Set = boolField(o, "is_active", true, errs)
	p.IsPublic.Value, p.IsPublic.Set = boolField(o, "is_public", true, errs)
	fields := []string{"name", "api_key", "api_key_secret_id", "endpoint_url", "description", "is_active", "is_public"}
	extraForbidden(o, fields, errs)
	if len(*errs) == n0 && p.APIKey.Value != nil && p.APIKeySecretID.Value != nil {
		*errs = append(*errs, httpx.ValueError(bothKeysDetail, "body"))
	}
	return map[string]any{}
}

func previewBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	key, set := str(o, "provider_key", 0, 0, false, errs)
	if !set {
		*errs = append(*errs, httpx.Missing("body", "provider_key"))
	} else if key != nil {
		in.providerKey = *key
	}
	in.apiKey, _ = str(o, "api_key", 0, 0, true, errs)
	in.endpointURL, _ = str(o, "endpoint_url", 0, 0, true, errs)
	return map[string]any{}
}

// instanceItem is ModelInstanceCreate (extra keys ignored) at loc.
func instanceItem(v any, loc []any, errs *[]httpx.FieldError) (domain.NewInstance, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		if _, isAbsent := v.(absent); isAbsent {
			*errs = append(*errs, httpx.Missing(loc...))
		} else {
			*errs = append(*errs, httpx.ModelAttributesType(loc...))
		}
		return domain.NewInstance{}, false
	}
	n0 := len(*errs)
	var n domain.NewInstance
	at := func(key string) []any { return append(append([]any{}, loc...), key) }
	reqUUID := func(key string) string {
		raw, present := o.Get(key)
		if !present {
			*errs = append(*errs, httpx.Missing(at(key)...))
			return ""
		}
		s, isStr := raw.(string)
		if !isStr {
			*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: at(key), Msg: "UUID input should be a string, bytes or UUID object"})
			return ""
		}
		id, fe := httpx.ValidateUUID(s, at(key)...)
		if fe != nil {
			*errs = append(*errs, *fe)
			return ""
		}
		return id
	}
	n.ProviderConfigID = reqUUID("provider_config_id")
	n.ModelSpecID = reqUUID("model_spec_id")
	if raw, present := o.Get("name"); !present {
		*errs = append(*errs, httpx.Missing(at("name")...))
	} else if s, isStr := raw.(string); isStr {
		n.Name = s
	} else {
		*errs = append(*errs, httpx.StringType(at("name")...))
	}
	if raw, present := o.Get("description"); present && raw != nil {
		if s, isStr := raw.(string); isStr {
			n.Description = &s
		} else {
			*errs = append(*errs, httpx.StringType(at("description")...))
		}
	}
	if raw, present := o.Get("is_public"); present {
		switch t := raw.(type) {
		case bool:
			n.IsPublic = t
		case string:
			if b, ok := httpx.ParseBool(t); ok {
				n.IsPublic = b
			} else {
				*errs = append(*errs, httpx.BoolParsing(at("is_public")...))
			}
		default:
			*errs = append(*errs, httpx.BoolType(at("is_public")...))
		}
	}
	return n, len(*errs) == n0
}

func instanceBody(v any, in *input, errs *[]httpx.FieldError) any {
	n, _ := instanceItem(v, []any{"body"}, errs)
	in.newInstance = n
	return map[string]any{}
}

func bulkBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	raw, present := o.Get("items")
	if !present {
		*errs = append(*errs, httpx.Missing("body", "items"))
		return nil
	}
	list, isList := raw.([]any)
	if !isList {
		*errs = append(*errs, httpx.ListType("body", "items"))
		return nil
	}
	if len(list) < 1 {
		*errs = append(*errs, httpx.FieldError{Type: "too_short", Loc: []any{"body", "items"},
			Msg: "List should have at least 1 item after validation, not 0",
			Ctx: wirejson.Object{{Key: "field_type", Value: "List"}, {Key: "min_length", Value: 1}, {Key: "actual_length", Value: 0}}})
		return nil
	}
	if len(list) > BulkMaxItems {
		*errs = append(*errs, httpx.FieldError{Type: "too_long", Loc: []any{"body", "items"},
			Msg: "List should have at most 500 items after validation, not " + strconv.Itoa(len(list)),
			Ctx: wirejson.Object{{Key: "field_type", Value: "List"}, {Key: "max_length", Value: BulkMaxItems}, {Key: "actual_length", Value: len(list)}}})
		return nil
	}
	for i, item := range list {
		n, _ := instanceItem(item, []any{"body", "items", i}, errs)
		in.bulk = append(in.bulk, n)
	}
	return map[string]any{}
}

func testBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	n0 := len(*errs)
	get := func(key string) uuid.UUID {
		raw, present := o.Get(key)
		if !present {
			*errs = append(*errs, httpx.Missing("body", key))
			return uuid.Nil
		}
		s, isStr := raw.(string)
		if !isStr {
			*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", key}, Msg: "UUID input should be a string, bytes or UUID object"})
			return uuid.Nil
		}
		id, fe := httpx.ValidateUUID(s, "body", key)
		if fe != nil {
			*errs = append(*errs, *fe)
			return uuid.Nil
		}
		return uuid.MustParse(id)
	}
	in.testConfig = get("provider_config_id")
	in.testSpec = get("model_spec_id")
	msg, set := str(o, "test_message", 0, 0, true, errs)
	if !set {
		d := "Hello, this is a test message."
		msg = &d
	}
	in.testMessage = msg
	_ = n0
	return map[string]any{}
}
