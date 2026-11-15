package handlers

import (
	"encoding/json"
	"math"
	"net/url"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
)

// int32Max is _INT32_MAX: context_window and max_output_tokens are INTEGER.
const int32Max = math.MaxInt32

// costCeiling is the Money bound lt=1e8.
const costCeiling = 100000000

func modelKinds() []string {
	return []string{service.KindChat, service.KindEmbedding, service.KindImage, service.KindVideo, service.KindDecision}
}

func providerSpecsQuery(q url.Values, in *input, errs fieldErrs) url.Values {
	in.isBuiltin = boolQuery(q, "is_builtin", errs)
	return nil
}

func uuidQuery(q url.Values, key string, errs fieldErrs) *uuid.UUID {
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
	return &u
}

func modelSpecsQuery(q url.Values, in *input, errs fieldErrs) url.Values {
	out := url.Values{}
	if id := uuidQuery(q, "provider_spec_id", errs); id != nil {
		in.modelFilter.ProviderSpecID = id
		out.Set("provider_spec_id", id.String())
	}
	if b := boolQuery(q, "is_active", errs); b != nil {
		in.modelFilter.IsActive = b
	}
	if k, ok := last(q, "kind"); ok {
		if slices.Contains(modelKinds(), k) {
			in.modelFilter.Kind = &k
			out.Set("kind", k)
		} else {
			*errs = append(*errs, httpx.EnumError(modelKinds(), "query", "kind"))
		}
	}
	return out
}

func byProviderQuery(q url.Values, in *input, errs fieldErrs) url.Values {
	in.modelFilter.IsActive = boolQuery(q, "is_active", errs)
	return nil
}

// pyValueRepr is repr() of a decoded JSON value.
func pyValueRepr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return service.PyRepr(x)
	case json.Number:
		return x.String()
	case wirejson.Float:
		return wirejson.FormatFloat(float64(x))
	case []any:
		parts := make([]string, len(x))
		for i, e := range x {
			parts[i] = pyValueRepr(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case wirejson.Object:
		parts := make([]string, len(x))
		for i, m := range x {
			parts[i] = service.PyRepr(m.Key) + ": " + pyValueRepr(m.Value)
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return ""
}

// moneyField is a Money | None field with ge=0, lt=1e8 (_parse_money then
// the decimal bounds).
func moneyField(o wirejson.Object, key string, errs fieldErrs) *money.Decimal {
	v, ok := o.Get(key)
	if !ok || v == nil {
		return nil
	}
	var text string
	switch x := v.(type) {
	case string:
		text = x
	case json.Number:
		text = x.String()
	case wirejson.Float:
		text = wirejson.FormatFloat(float64(x))
	}
	d, err := money.Parse(text)
	if _, isBool := v.(bool); isBool || text == "" || err != nil {
		*errs = append(*errs, httpx.ValueError(pyValueRepr(v)+" is not a money amount", "body", key))
		return nil
	}
	if d.Cmp(money.Zero()) < 0 {
		*errs = append(*errs, httpx.GreaterThanEqual(0, "body", key))
		return nil
	}
	if d.Cmp(money.FromInt(costCeiling)) >= 0 {
		*errs = append(*errs, httpx.LessThan(costCeiling, "body", key))
		return nil
	}
	return &d
}

// positiveInt is an int | None field with gt=0, le=_INT32_MAX.
func positiveInt(o wirejson.Object, key string, errs fieldErrs) *int {
	before := len(*errs)
	n, _ := intField(o, key, math.MinInt64, math.MaxInt64, errs)
	if n == nil || len(*errs) > before {
		return nil
	}
	if *n <= 0 {
		*errs = append(*errs, httpx.GreaterThan(0, "body", key))
		return nil
	}
	if *n > int32Max {
		*errs = append(*errs, httpx.LessThanEqual(int32Max, "body", key))
		return nil
	}
	return n
}

// requiredStr is a required str field.
func requiredStr(o wirejson.Object, key string, errs fieldErrs) string {
	v, set := str(o, key, 0, 0, false, errs)
	if !set {
		*errs = append(*errs, httpx.Missing("body", key))
		return ""
	}
	if v == nil {
		return ""
	}
	return *v
}

// strictBool is a bool field that refuses null.
func strictBool(o wirejson.Object, key string, errs fieldErrs) *bool {
	v, ok := o.Get(key)
	if !ok {
		return nil
	}
	if v == nil {
		*errs = append(*errs, httpx.BoolType("body", key))
		return nil
	}
	b, _ := boolField(o, key, errs)
	return b
}

func modelCreateBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	n := &in.newModel
	before := len(*errs)
	if raw, has := o.Get("provider_spec_id"); !has {
		*errs = append(*errs, httpx.Missing("body", "provider_spec_id"))
	} else if s, isStr := raw.(string); !isStr {
		*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", "provider_spec_id"}, Msg: "UUID input should be a string, bytes or UUID object"})
	} else if id, fe := httpx.ValidateUUID(s, "body", "provider_spec_id"); fe != nil {
		*errs = append(*errs, *fe)
	} else {
		n.ProviderSpecID = uuid.MustParse(id)
	}
	n.ModelName = requiredStr(o, "model_name", errs)
	name := requiredStr(o, "display_name", errs)
	f := &n.Fields
	f.DisplayName = &name
	f.Description, _ = str(o, "description", 0, 0, true, errs)
	kind := service.KindChat
	if k, has := o.Get("kind"); has {
		if s, isStr := k.(string); isStr && slices.Contains(modelKinds(), s) {
			kind = s
		} else {
			*errs = append(*errs, httpx.EnumError(modelKinds(), "body", "kind"))
		}
	}
	f.Kind = &kind
	f.ContextWindow = positiveInt(o, "context_window", errs)
	f.MaxOutputTokens = positiveInt(o, "max_output_tokens", errs)
	f.InputCostPerToken = moneyField(o, "input_cost_per_token", errs)
	f.OutputCostPerToken = moneyField(o, "output_cost_per_token", errs)
	f.CachedInputCostPerToken = moneyField(o, "cached_input_cost_per_token", errs)
	f.CacheCreationInputCostPerToken = moneyField(o, "cache_creation_input_cost_per_token", errs)
	f.DefaultContextStrategy, _ = str(o, "default_context_strategy", 0, 0, true, errs)
	active := true
	if b := strictBool(o, "is_active", errs); b != nil {
		active = *b
	}
	f.IsActive = &active
	if len(*errs) == before && service.PricedPerToken(kind) && f.ContextWindow == nil {
		*errs = append(*errs, httpx.ValueError("a "+kind+" model requires context_window", "body"))
	}
}

func modelUpdateBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	f := &in.modelFields
	f.DisplayName, _ = str(o, "display_name", 0, 0, true, errs)
	f.Description, _ = str(o, "description", 0, 0, true, errs)
	f.ContextWindow = positiveInt(o, "context_window", errs)
	f.MaxOutputTokens = positiveInt(o, "max_output_tokens", errs)
	f.InputCostPerToken = moneyField(o, "input_cost_per_token", errs)
	f.OutputCostPerToken = moneyField(o, "output_cost_per_token", errs)
	f.CachedInputCostPerToken = moneyField(o, "cached_input_cost_per_token", errs)
	f.CacheCreationInputCostPerToken = moneyField(o, "cache_creation_input_cost_per_token", errs)
	f.DefaultContextStrategy, _ = str(o, "default_context_strategy", 0, 0, true, errs)
	f.IsActive, _ = boolField(o, "is_active", errs)
}

// extraForbidden reports the keys of o a model with extra="forbid" does not declare.
func extraForbidden(o wirejson.Object, fields []string, errs fieldErrs) {
	for _, m := range o {
		if !slices.Contains(fields, m.Key) {
			*errs = append(*errs, httpx.ExtraForbidden("body", m.Key))
		}
	}
}

func uuidBodyField(o wirejson.Object, key string, errs fieldErrs) (value *string, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil {
		return nil, true
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", key}, Msg: "UUID input should be a string, bytes or UUID object"})
		return nil, true
	}
	id, fe := httpx.ValidateUUID(s, "body", key)
	if fe != nil {
		*errs = append(*errs, *fe)
		return nil, true
	}
	return &id, true
}

func wsTrusts() []string { return []string{"private", "community"} }

func wsRegistryCreateBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	n := &in.registry
	if name, set := str(o, "name", 1, 255, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "name"))
	} else if name != nil {
		n.Name = *name
	}
	n.Description, _ = str(o, "description", 0, 0, true, errs)
	n.RegistryType = "skills"
	if rt, _ := literalField(o, "registry_type", []string{"skills", "agents"}, false, errs); rt != nil {
		n.RegistryType = *rt
	}
	if st, set := literalField(o, "source_type", []string{"url", "github"}, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "source_type"))
	} else if st != nil {
		n.SourceType = *st
	}
	if u, set := str(o, "source_url", 1, 0, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "source_url"))
	} else if u != nil {
		n.SourceURL = *u
	}
	n.SourceRef, _ = str(o, "source_ref", 0, 255, true, errs)
	n.SourcePath, _ = str(o, "source_path", 0, 0, true, errs)
	n.Trust, n.Mode = "private", "mirror"
	if t, _ := literalField(o, "trust", wsTrusts(), false, errs); t != nil {
		n.Trust = *t
	}
	if m, _ := literalField(o, "mode", modes(), false, errs); m != nil {
		n.Mode = *m
	}
	n.CredentialsSecretRef, _ = uuidBodyField(o, "credentials_secret_id", errs)
	extraForbidden(o, []string{"name", "description", "registry_type", "source_type", "source_url", "source_ref",
		"source_path", "trust", "mode", "credentials_secret_id"}, errs)
	n.Scope = "workspace"
}

func wsRegistryUpdateBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	p := &in.registryPatch
	p.Name.Value, p.Name.Set = str(o, "name", 1, 255, true, errs)
	p.Description.Value, p.Description.Set = str(o, "description", 0, 0, true, errs)
	p.SourceURL.Value, p.SourceURL.Set = str(o, "source_url", 1, 0, true, errs)
	p.SourceRef.Value, p.SourceRef.Set = str(o, "source_ref", 0, 255, true, errs)
	p.SourcePath.Value, p.SourcePath.Set = str(o, "source_path", 0, 0, true, errs)
	p.IsActive.Value, p.IsActive.Set = boolField(o, "is_active", errs)
	p.Trust.Value, p.Trust.Set = literalField(o, "trust", wsTrusts(), true, errs)
	p.Mode.Value, p.Mode.Set = literalField(o, "mode", modes(), true, errs)
	p.CredentialsSecretRef.Value, p.CredentialsSecretRef.Set = uuidBodyField(o, "credentials_secret_id", errs)
	extraForbidden(o, []string{"name", "description", "source_url", "source_ref", "source_path", "is_active",
		"trust", "mode", "credentials_secret_id"}, errs)
}
