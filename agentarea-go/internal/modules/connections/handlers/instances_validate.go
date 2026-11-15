package handlers

import (
	"encoding/json"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// instanceInput is an instance route's body, validated.
type instanceInput struct {
	create service.InstanceCreate
	server catalogapi.MCPSpecNew
	patch  service.InstancePatchIn
	shared bool
	// check is /check's json_spec: the body's, else the body.
	check any
}

// fields checks one model's fields at a location.
type fields struct {
	o    wirejson.Object
	base []any
	errs *[]httpx.FieldError
}

func (f fields) loc(key ...any) []any { return append(append([]any{}, f.base...), key...) }

func (f fields) add(e httpx.FieldError) { *f.errs = append(*f.errs, e) }

func (f fields) str(key string, required, nullable bool, minLen, maxLen int) (*string, bool) {
	v, has := f.o.Get(key)
	if !has {
		if required {
			f.add(httpx.Missing(f.loc(key)...))
			return nil, false
		}
		return nil, true
	}
	if v == nil && nullable {
		return nil, true
	}
	s, ok := v.(string)
	if !ok {
		f.add(httpx.StringType(f.loc(key)...))
		return nil, false
	}
	n := utf8.RuneCountInString(s)
	if minLen > 0 && n < minLen {
		f.add(httpx.StringTooShort(minLen, f.loc(key)...))
		return nil, false
	}
	if maxLen > 0 && n > maxLen {
		f.add(httpx.StringTooLong(maxLen, f.loc(key)...))
		return nil, false
	}
	return &s, true
}

// name is a 1..255 name stripped by its validator.
func (f fields) name(required bool) (*string, bool) {
	s, ok := f.str("name", required, !required, 1, 255)
	if !ok || s == nil {
		return s, ok
	}
	t := strings.TrimSpace(*s)
	if t == "" {
		f.add(httpx.ValueError("name cannot be empty or whitespace", f.loc("name")...))
		return nil, false
	}
	return &t, true
}

func (f fields) dict(key string, required, nullable bool) (map[string]any, bool) {
	v, has := f.o.Get(key)
	if !has {
		if required {
			f.add(httpx.Missing(f.loc(key)...))
			return nil, false
		}
		return nil, true
	}
	if v == nil && nullable {
		return nil, true
	}
	o, ok := v.(wirejson.Object)
	if !ok {
		f.add(httpx.DictType(f.loc(key)...))
		return nil, false
	}
	return toMap(o), true
}

func (f fields) strList(key string, nullable bool) ([]any, bool) {
	v, has := f.o.Get(key)
	if !has || (v == nil && nullable) {
		return nil, true
	}
	l, ok := v.([]any)
	if !ok {
		f.add(httpx.ListType(f.loc(key)...))
		return nil, false
	}
	good := true
	for i, x := range l {
		if _, ok := x.(string); !ok {
			f.add(httpx.StringType(f.loc(key, i)...))
			good = false
		}
	}
	return l, good
}

func (f fields) dictList(key string) ([]any, bool) {
	v, has := f.o.Get(key)
	if !has || v == nil {
		return nil, true
	}
	l, ok := v.([]any)
	if !ok {
		f.add(httpx.ListType(f.loc(key)...))
		return nil, false
	}
	out := make([]any, 0, len(l))
	good := true
	for i, x := range l {
		o, ok := x.(wirejson.Object)
		if !ok {
			f.add(httpx.DictType(f.loc(key, i)...))
			good = false
			continue
		}
		out = append(out, toMap(o))
	}
	return out, good
}

func (f fields) boolean(key string) (bool, bool) {
	v, has := f.o.Get(key)
	if !has {
		return false, true
	}
	switch t := v.(type) {
	case bool:
		return t, true
	case string:
		if b, ok := httpx.ParseBool(t); ok {
			return b, true
		}
		f.add(httpx.BoolParsing(f.loc(key)...))
		return false, false
	case json.Number:
		switch t.String() {
		case "0":
			return false, true
		case "1":
			return true, true
		}
		f.add(httpx.BoolParsing(f.loc(key)...))
		return false, false
	}
	f.add(httpx.BoolType(f.loc(key)...))
	return false, false
}

// specCheck runs a json_spec's validators; a refusal is a value error at the field.
func (f fields) specCheck(key string, spec map[string]any, kind domain.SpecKind) bool {
	if spec == nil {
		return true
	}
	if msg := domain.JSONSpecError(spec, kind); msg != "" {
		f.add(httpx.ValueError(msg, f.loc(key)...))
		return false
	}
	return true
}

func (f fields) extra(allowed ...string) {
	for _, m := range f.o {
		found := false
		for _, a := range allowed {
			if m.Key == a {
				found = true
				break
			}
		}
		if !found {
			f.add(httpx.ExtraForbidden(f.loc(m.Key)...))
		}
	}
}

// contextSecret is ContextSecret: 32..512 characters, or null.
func (f fields) contextSecret() (*string, bool, bool) {
	_, has := f.o.Get("context_secret")
	s, ok := f.str("context_secret", false, true, domain.ContextSecretMinLength, domain.ContextSecretMaxLength)
	return s, has, ok
}

// instanceCreateBody is MCPServerInstanceCreate.
func instanceCreateBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	f := fields{o: o, base: []any{"body"}, errs: errs}
	before := len(*errs)
	name, _ := f.name(true)
	desc, _ := f.str("description", false, true, 0, 0)
	var specID string
	if raw, has := o.Get("server_spec_id"); !has {
		f.add(httpx.Missing("body", "server_spec_id"))
	} else if s, isStr := raw.(string); !isStr {
		f.add(httpx.FieldError{Type: "uuid_type", Loc: []any{"body", "server_spec_id"}, Msg: "UUID input should be a string, bytes or UUID object"})
	} else if id, fe := httpx.ValidateUUID(s, "body", "server_spec_id"); fe != nil {
		f.add(*fe)
	} else {
		specID = id
	}
	spec, specOK := f.dict("json_spec", true, false)
	if specOK {
		f.specCheck("json_spec", spec, domain.InstanceCreateSpec)
	}
	auth, _ := f.str("auth_config_id", false, true, 0, 0)
	secret, _, _ := f.contextSecret()
	f.extra("name", "description", "server_spec_id", "json_spec", "auth_config_id", "context_secret")
	if len(*errs) > before {
		return nil
	}
	in.instance.create = service.InstanceCreate{Name: *name, Description: desc, ServerSpecID: specID,
		JSONSpec: spec, AuthConfigID: auth, ContextSecret: secret}
	return o
}

// instanceUpdateBody is MCPServerInstanceUpdate: unset fields are unchanged.
func instanceUpdateBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	f := fields{o: o, base: []any{"body"}, errs: errs}
	before := len(*errs)
	p := service.InstancePatchIn{}
	if raw, has := o.Get("name"); has {
		if raw == nil {
			f.add(httpx.ValueError("may be omitted, but not set to null", "body", "name"))
		} else {
			p.Name, _ = f.name(false)
		}
	}
	_, p.DescriptionSet = o.Get("description")
	p.Description, _ = f.str("description", false, true, 0, 0)
	if raw, has := o.Get("json_spec"); has {
		if raw == nil {
			f.add(httpx.ValueError("may be omitted, but not set to null", "body", "json_spec"))
		} else if spec, ok := f.dict("json_spec", false, false); ok && f.specCheck("json_spec", spec, domain.InstanceUpdateSpec) {
			p.JSONSpec = spec
		}
	}
	p.ContextSecret, p.ContextSecretSet, _ = f.contextSecret()
	if _, has := o.Get("cost"); has {
		p.CostSet = true
		if cost, ok := f.dict("cost", false, true); ok && cost != nil {
			if msg := domain.ConnectionCostError(cost); msg != "" {
				f.add(httpx.ValueError(msg, "body", "cost"))
			}
			p.Cost = cost
		}
	}
	f.extra("name", "description", "json_spec", "context_secret", "cost")
	if len(*errs) > before {
		return nil
	}
	in.instance.patch = p
	return o
}

// withSpecBody is MCPServerConnectionCreateRequest: a strict MCPServerCreate
// and a lenient instance (the route model_constructs it).
func withSpecBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	before := len(*errs)
	var server catalogapi.MCPSpecNew
	if raw, has := o.Get("server"); !has {
		*errs = append(*errs, httpx.Missing("body", "server"))
	} else if so, isObj := raw.(wirejson.Object); !isObj {
		*errs = append(*errs, httpx.ModelAttributesType("body", "server"))
	} else {
		server = serverCreate(fields{o: so, base: []any{"body", "server"}, errs: errs})
	}
	var inst service.InstanceCreate
	if raw, has := o.Get("instance"); !has {
		*errs = append(*errs, httpx.Missing("body", "instance"))
	} else if io, isObj := raw.(wirejson.Object); !isObj {
		*errs = append(*errs, httpx.ModelAttributesType("body", "instance"))
	} else {
		f := fields{o: io, base: []any{"body", "instance"}, errs: errs}
		name, _ := f.str("name", true, false, 0, 0)
		inst.Description, _ = f.str("description", false, true, 0, 0)
		inst.JSONSpec, _ = f.dict("json_spec", false, false)
		inst.AuthConfigID, _ = f.str("auth_config_id", false, true, 0, 0)
		inst.ContextSecret, _, _ = f.contextSecret()
		if name != nil {
			inst.Name = *name
		}
		if inst.JSONSpec == nil {
			inst.JSONSpec = map[string]any{}
		}
	}
	if len(*errs) > before {
		return nil
	}
	in.instance.server, in.instance.create = server, inst
	return o
}

// serverCreate is MCPServerCreate.
func serverCreate(f fields) catalogapi.MCPSpecNew {
	var n catalogapi.MCPSpecNew
	if name, _ := f.name(true); name != nil {
		n.Name = *name
	}
	if d, _ := f.str("description", true, false, 0, 0); d != nil {
		n.Description = *d
	}
	if img, ok := f.str("docker_image_url", false, true, 0, 0); ok && img != nil {
		if msg := domain.ImageReferenceError(*img); msg != "" {
			f.add(httpx.ValueError(msg, f.loc("docker_image_url")...))
		}
		n.DockerImageURL = img
	}
	n.RemoteURL, _ = f.str("remote_url", false, true, 0, 0)
	n.Version = "1.0.0"
	if ver, _ := f.str("version", false, false, 0, 0); ver != nil {
		n.Version = *ver
	}
	n.Tags = []any{}
	if tags, _ := f.strList("tags", false); tags != nil {
		n.Tags = tags
	}
	f.boolean("is_public")
	n.EnvSchema, _ = f.dictList("env_schema")
	if n.EnvSchema == nil {
		n.EnvSchema = []any{}
	}
	n.Cmd, _ = f.strList("cmd", true)
	if spec, ok := f.dict("json_spec", false, true); ok && f.specCheck("json_spec", spec, domain.ServerSpec) {
		n.JSONSpec = spec
	}
	n.RegistryURL, _ = f.str("registry_url", false, true, 0, 0)
	f.extra("name", "description", "docker_image_url", "remote_url", "version", "tags", "is_public",
		"env_schema", "cmd", "json_spec", "registry_url")
	return n
}

// withSpecInstanceError is the MCPServerInstanceCreate the service builds for
// with-spec's instance: its refusal is a 400.
func withSpecInstanceError(in service.InstanceCreate) error {
	name := strings.TrimSpace(in.Name)
	switch {
	case utf8.RuneCountInString(in.Name) < 1:
		return &domain.Invalid{Msg: "name: String should have at least 1 character"}
	case utf8.RuneCountInString(in.Name) > 255:
		return &domain.Invalid{Msg: "name: String should have at most 255 characters"}
	case name == "":
		return &domain.Invalid{Msg: "name: Value error, name cannot be empty or whitespace"}
	}
	if msg := domain.JSONSpecError(in.JSONSpec, domain.InstanceCreateSpec); msg != "" {
		return &domain.Invalid{Msg: "json_spec: Value error, " + msg}
	}
	return nil
}

// sharingBody is ConnectionSharingRequest.
func sharingBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	f := fields{o: o, base: []any{"body"}, errs: errs}
	if _, has := o.Get("shared"); !has {
		f.add(httpx.Missing("body", "shared"))
		return nil
	}
	b, ok := f.boolean("shared")
	if !ok {
		return nil
	}
	in.instance.shared = b
	return o
}

// anyDictBody is a `data: dict` body.
func anyDictBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := v.(wirejson.Object)
	if !ok {
		if _, isAbsent := v.(absent); isAbsent {
			*errs = append(*errs, httpx.Missing("body"))
		} else {
			*errs = append(*errs, httpx.DictType("body"))
		}
		return nil
	}
	if spec, has := o.Get("json_spec"); has {
		in.instance.check = plain(spec)
	} else {
		in.instance.check = toMap(o)
	}
	return o
}
