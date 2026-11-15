package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"net/url"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

// input is what a route's parameters and body validated to.
type input struct {
	force           bool
	limit, offset   int32
	activeOnly      bool
	registryType    string
	scope           string
	browse          domain.BrowseFilter
	sort            *string
	protocolSet     bool
	hostingSet      bool
	pricingSet      bool
	q, tag          string
	updateAvailable *bool
	registry        domain.NewRegistry
	priority        *int
	registryPatch   domain.RegistryPatch
	item            domain.NewItem
	itemPatch       domain.ItemPatch
	isBuiltin       *bool
	modelFilter     service.ModelFilter
	newModel        service.NewModelSpec
	modelFields     store.SpecFields
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

type fieldErrs = *[]httpx.FieldError

// request is one route's parameters: path UUIDs, query, body, in FastAPI's
// order; every error is reported in one 422.
type request struct {
	pathUUIDs []string
	query     func(q url.Values, in *input, errs fieldErrs) url.Values
	body      func(v any, in *input, errs fieldErrs)
}

func (rq request) middleware(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			var fes []httpx.FieldError
			var in input
			if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
				fes = append(fes, *fe)
			}
			for _, name := range rq.pathUUIDs {
				if _, fe := httpx.ValidateUUID(chi.URLParam(r, name), "path", name); fe != nil {
					fes = append(fes, *fe)
				}
			}
			canonical := url.Values{}
			if rq.query != nil {
				if q := rq.query(r.URL.Query(), &in, &fes); q != nil {
					canonical = q
				}
			}
			r.URL.RawQuery = canonical.Encode()
			if rq.body != nil {
				v, err := readBody(r)
				if err != nil {
					errs.Write(w, r, err)
					return
				}
				rq.body(v, &in, &fes)
			}
			if err := httpx.Validation(fes...); err != nil {
				errs.Write(w, r, err)
				return
			}
			if rq.body != nil {
				raw := []byte("{}")
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

// MaxPageLimit and DefaultPageLimit are the catalog's limit Query bounds.
const (
	MaxPageLimit     = 500
	DefaultPageLimit = 50
)

func page(q url.Values, in *input, errs fieldErrs) {
	in.limit, in.offset = DefaultPageLimit, 0
	if v, ok := last(q, "limit"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: MaxPageLimit, HasLe: true}, "query", "limit")
		if fe != nil {
			*errs = append(*errs, *fe)
		} else {
			in.limit = int32(n)
		}
	}
	if v, ok := last(q, "offset"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 0, HasGe: true, Le: httpx.MaxOffset, HasLe: true}, "query", "offset")
		if fe != nil {
			*errs = append(*errs, *fe)
		} else {
			in.offset = int32(n)
		}
	}
}

func boolQuery(q url.Values, key string, errs fieldErrs) *bool {
	v, ok := last(q, key)
	if !ok {
		return nil
	}
	b, valid := httpx.ParseBool(v)
	if !valid {
		*errs = append(*errs, httpx.BoolParsing("query", key))
		return nil
	}
	return &b
}

func literalQuery(q url.Values, key string, choices []string, errs fieldErrs) (string, bool) {
	v, ok := last(q, key)
	if !ok {
		return "", false
	}
	for _, c := range choices {
		if v == c {
			return v, true
		}
	}
	*errs = append(*errs, httpx.LiteralError(choices, "query", key))
	return "", false
}

func scopes() []string { return []string{"platform", "workspace"} }
func modes() []string  { return []string{"mirror", "upstream"} }
func trusts() []string { return []string{"official", "verified", "community", "private"} }

func listRegistriesQuery(q url.Values, in *input, errs fieldErrs) url.Values {
	if b := boolQuery(q, "active_only", errs); b != nil {
		in.activeOnly = *b
	}
	in.registryType, _ = last(q, "registry_type")
	in.scope, _ = literalQuery(q, "scope", scopes(), errs)
	return nil
}

func browseQuery(q url.Values, in *input, errs fieldErrs) url.Values {
	rt, ok := last(q, "registry_type")
	if !ok {
		*errs = append(*errs, httpx.Missing("query", "registry_type"))
	}
	in.browse.RegistryType = rt
	in.browse.Query, _ = last(q, "q")
	in.browse.Category, _ = last(q, "category")
	in.browse.Protocol, in.protocolSet = literalQuery(q, "protocol", domain.Protocols(), errs)
	in.browse.Hosting, in.hostingSet = literalQuery(q, "hosting", domain.Hostings(), errs)
	in.browse.Pricing, in.pricingSet = literalQuery(q, "pricing", domain.Pricings(), errs)
	if s, ok := last(q, "sort"); ok {
		in.sort = &s
	}
	page(q, in, errs)
	return url.Values{"registry_type": {rt}}
}

func searchQuery(q url.Values, in *input, errs fieldErrs) url.Values {
	in.q, _ = last(q, "q")
	in.tag, _ = last(q, "tag")
	in.updateAvailable = boolQuery(q, "update_available", errs)
	page(q, in, errs)
	return nil
}

func pageQuery(q url.Values, in *input, errs fieldErrs) url.Values {
	page(q, in, errs)
	return nil
}

func literalField(o wirejson.Object, key string, choices []string, nullable bool, errs fieldErrs) (value *string, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil && nullable {
		return nil, true
	}
	if s, isStr := v.(string); isStr {
		for _, c := range choices {
			if s == c {
				return &s, true
			}
		}
	}
	*errs = append(*errs, httpx.LiteralError(choices, "body", key))
	return nil, true
}

func boolField(o wirejson.Object, key string, errs fieldErrs) (value *bool, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	switch x := v.(type) {
	case nil:
		return nil, true
	case bool:
		return &x, true
	case string:
		if b, valid := httpx.ParseBool(x); valid {
			return &b, true
		}
		*errs = append(*errs, httpx.BoolParsing("body", key))
	case json.Number:
		switch string(x) {
		case "0":
			f := false
			return &f, true
		case "1":
			t := true
			return &t, true
		}
		*errs = append(*errs, httpx.BoolParsing("body", key))
	case wirejson.Float:
		switch float64(x) {
		case 0:
			f := false
			return &f, true
		case 1:
			t := true
			return &t, true
		}
		*errs = append(*errs, httpx.BoolParsing("body", key))
	default:
		*errs = append(*errs, httpx.BoolType("body", key))
	}
	return nil, true
}

// dictField is a dict[str, Any] field, kept as its JSON.
func dictField(o wirejson.Object, key string, nullable bool, errs fieldErrs) (value json.RawMessage, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil && nullable {
		return nil, true
	}
	obj, isObj := v.(wirejson.Object)
	if !isObj {
		*errs = append(*errs, httpx.DictType("body", key))
		return nil, true
	}
	raw, err := wirejson.Marshal(obj, wirejson.Compact)
	if err != nil {
		*errs = append(*errs, httpx.DictType("body", key))
		return nil, true
	}
	return raw, true
}

// tagsField is a list[str] field.
func tagsField(o wirejson.Object, key string, nullable bool, errs fieldErrs) (value json.RawMessage, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil && nullable {
		return nil, true
	}
	arr, isArr := v.([]any)
	if !isArr {
		*errs = append(*errs, httpx.ListType("body", key))
		return nil, true
	}
	tags := make([]string, 0, len(arr))
	bad := false
	for i, t := range arr {
		s, isStr := t.(string)
		if !isStr {
			*errs = append(*errs, httpx.StringType("body", key, i))
			bad = true
			continue
		}
		tags = append(tags, s)
	}
	if bad {
		return nil, true
	}
	raw, _ := json.Marshal(tags)
	return raw, true
}

func registryCreateBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	n := &in.registry
	if name, set := str(o, "name", 0, 0, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "name"))
	} else if name != nil {
		n.Name = *name
	}
	n.Description, _ = str(o, "description", 0, 0, true, errs)
	if rt, set := str(o, "registry_type", 0, 0, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "registry_type"))
	} else if rt != nil {
		n.RegistryType = *rt
	}
	if st, set := str(o, "source_type", 0, 0, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "source_type"))
	} else if st != nil {
		n.SourceType = *st
	}
	if u, _ := str(o, "source_url", 0, 0, true, errs); u != nil {
		n.SourceURL = *u
	}
	in.priority, _ = intField(o, "recommendation_priority", 0, math.MaxInt64, errs)
	n.Mode, n.Trust = "mirror", "official"
	if m, _ := literalField(o, "mode", modes(), false, errs); m != nil {
		n.Mode = *m
	}
	if t, _ := literalField(o, "trust", trusts(), false, errs); t != nil {
		n.Trust = *t
	}
	n.SourceRef, _ = str(o, "source_ref", 0, 255, true, errs)
	n.SourcePath, _ = str(o, "source_path", 0, 0, true, errs)
	n.Scope = "platform"
}

func registryUpdateBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	p := &in.registryPatch
	p.Name.Value, p.Name.Set = str(o, "name", 0, 0, true, errs)
	p.Description.Value, p.Description.Set = str(o, "description", 0, 0, true, errs)
	p.SourceURL.Value, p.SourceURL.Set = str(o, "source_url", 0, 0, true, errs)
	p.IsActive.Value, p.IsActive.Set = boolField(o, "is_active", errs)
	p.RecommendationPriority.Value, p.RecommendationPriority.Set = intField(o, "recommendation_priority", 0, math.MaxInt64, errs)
	p.Mode.Value, p.Mode.Set = literalField(o, "mode", modes(), true, errs)
	p.Trust.Value, p.Trust.Set = literalField(o, "trust", trusts(), true, errs)
}

func itemCreateBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	n := &in.item
	if ext, set := str(o, "external_id", 1, 500, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "external_id"))
	} else if ext != nil {
		n.ExternalID = *ext
	}
	if name, set := str(o, "name", 1, 255, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "name"))
	} else if name != nil {
		n.Name = *name
	}
	n.Description, _ = str(o, "description", 0, 0, true, errs)
	n.Version, _ = str(o, "version", 0, 100, true, errs)
	n.Spec, _ = dictField(o, "spec", false, errs)
	if n.Spec == nil {
		n.Spec = json.RawMessage("{}")
	}
	n.Tags, _ = tagsField(o, "tags", false, errs)
	if n.Tags == nil {
		n.Tags = json.RawMessage("[]")
	}
	n.RecommendationRank, _ = intField(o, "recommendation_rank", 0, math.MaxInt64, errs)
}

func itemUpdateBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	p := &in.itemPatch
	p.ExternalID.Value, p.ExternalID.Set = str(o, "external_id", 1, 500, true, errs)
	p.Name.Value, p.Name.Set = str(o, "name", 1, 255, true, errs)
	p.Description.Value, p.Description.Set = str(o, "description", 0, 0, true, errs)
	p.Version.Value, p.Version.Set = str(o, "version", 0, 100, true, errs)
	p.Spec.Value, p.Spec.Set = dictField(o, "spec", true, errs)
	p.Tags.Value, p.Tags.Set = tagsField(o, "tags", true, errs)
}

func forceQuery(q url.Values, in *input, errs fieldErrs) url.Values {
	if b := boolQuery(q, "force", errs); b != nil {
		in.force = *b
	}
	return nil
}
