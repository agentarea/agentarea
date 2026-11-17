package handlers

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// clientMaxListLimit is list_clients' limit bound.
const clientMaxListLimit = 1000

// clientMaxPrefix is the namespace_prefix column's width.
const clientMaxPrefix = 64

// clientInput is what a client route validated to.
type clientInput struct {
	limit, offset int32
	name          string
	description   *string
	kind          string
	patch         service.ClientPatch
	ref           string
	prefix        *string
	list          *[]string
}

func clientLast(q map[string][]string, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

func clientListQuery(q map[string][]string, in *input, errs *[]httpx.FieldError) {
	ci := clientInput{limit: 100}
	if v, ok := clientLast(q, "limit"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: clientMaxListLimit, HasLe: true}, "query", "limit")
		if fe != nil {
			*errs = append(*errs, *fe)
		} else {
			ci.limit = int32(n)
		}
	}
	if v, ok := clientLast(q, "offset"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 0, HasGe: true, Le: httpx.MaxOffset, HasLe: true}, "query", "offset")
		if fe != nil {
			*errs = append(*errs, *fe)
		} else {
			ci.offset = int32(n)
		}
	}
	in.area = ci
}

// clientCreateBody is ClientCreate (extra="forbid").
func clientCreateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	ci := clientInput{kind: "harness"}
	name, set := str(o, "name", 1, 255, false, errs)
	switch {
	case !set:
		*errs = append(*errs, httpx.Missing("body", "name"))
	case name != nil:
		ci.name = pyStrip(*name)
		if ci.name == "" {
			*errs = append(*errs, httpx.ValueError("name cannot be empty or whitespace", "body", "name"))
		}
	}
	ci.description, _ = str(o, "description", 0, 1000, true, errs)
	if kind, _ := str(o, "kind", 0, 32, false, errs); kind != nil {
		ci.kind = *kind
	}
	extraForbidden(o, []string{"name", "description", "kind"}, errs)
	in.area = ci
}

func clientNotNull(o wirejson.Object, key string, errs *[]httpx.FieldError) bool {
	if v, ok := o.Get(key); ok && v == nil {
		*errs = append(*errs, httpx.ValueError("may be omitted, but not set to null", "body", key))
		return true
	}
	return false
}

// clientUpdateBody is ClientUpdate (extra="forbid", exclude_unset).
func clientUpdateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var p service.ClientPatch
	if !clientNotNull(o, "name", errs) {
		p.Name, _ = str(o, "name", 1, 255, false, errs)
	}
	p.Description.Value, p.Description.Set = str(o, "description", 0, 1000, true, errs)
	if !clientNotNull(o, "kind", errs) {
		p.Kind, _ = str(o, "kind", 0, 32, false, errs)
	}
	p.DefaultModel.Value, p.DefaultModel.Set = str(o, "default_model", 0, 255, true, errs)
	if !clientNotNull(o, "allow_domains", errs) {
		if domains, ok := clientStrList(o, "allow_domains", errs); ok && domains != nil {
			if msg := domain.ClientCheckDomains(*domains); msg != "" {
				*errs = append(*errs, httpx.ValueError(msg, "body", "allow_domains"))
			} else {
				p.AllowDomains = domains
			}
		}
	}
	if !clientNotNull(o, "sandbox", errs) {
		p.Sandbox, _ = boolField(o, "sandbox", errs)
	}
	extraForbidden(o, []string{"name", "description", "kind", "default_model", "allow_domains", "sandbox"}, errs)
	in.area = clientInput{patch: p}
}

// clientStrList is a list[str] | None field: ok when it validated (nil for null or absent).
func clientStrList(o wirejson.Object, key string, errs *[]httpx.FieldError) (*[]string, bool) {
	v, present := o.Get(key)
	if !present || v == nil {
		return nil, true
	}
	items, isList := v.([]any)
	if !isList {
		*errs = append(*errs, httpx.ListType("body", key))
		return nil, false
	}
	out := make([]string, 0, len(items))
	valid := true
	for i, it := range items {
		s, isStr := it.(string)
		if !isStr {
			*errs = append(*errs, httpx.StringType("body", key, i))
			valid = false
			continue
		}
		out = append(out, s)
	}
	if !valid {
		return nil, false
	}
	return &out, true
}

// clientAssociationBody is AssociationBody, or with links McpInstanceAssociationBody
// and OpenAPIConnectionAssociationBody; extra keys are ignored.
func clientAssociationBody(links bool) func(v any, in *input, errs *[]httpx.FieldError) {
	return func(v any, in *input, errs *[]httpx.FieldError) {
		o, ok := model(v, errs)
		if !ok {
			return
		}
		var ci clientInput
		id, set := str(o, "id", 0, 0, false, errs)
		switch {
		case !set:
			*errs = append(*errs, httpx.Missing("body", "id"))
		case id != nil:
			ci.ref = *id
		}
		if links {
			ci.prefix, _ = str(o, "namespace_prefix", 0, clientMaxPrefix, true, errs)
			ci.list, _ = clientStrList(o, "allowed_tools", errs)
		}
		in.area = ci
	}
}

// clientToolsetBody is PlatformToolsetAssociationBody.
func clientToolsetBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var ci clientInput
	name, set := str(o, "name", 0, 0, false, errs)
	switch {
	case !set:
		*errs = append(*errs, httpx.Missing("body", "name"))
	case name != nil:
		ci.ref = *name
	}
	ci.list, _ = clientStrList(o, "disabled_methods", errs)
	in.area = ci
}
