package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// input is what a route's parameters and body validated to, kept in the
// request context for the strict handler (the generated binding cannot tell
// an absent key from null, nor report pydantic's errors).
type input struct {
	auth          domain.AuthConfigNew
	patch         domain.AuthConfigPatch
	link          linkNew
	limit, offset int32
	status        *string
	pattern       *string
	instance      instanceInput
}

// linkNew is OAuthLinkCreateRequest, validated.
type linkNew struct {
	instance uuid.UUID
	access   string
	provider map[string]any
	days     *int
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

// absent is a request body FastAPI saw none of.
type absent struct{}

// request is one route's parameters: path UUIDs, then query, then body, in
// FastAPI's order; every error is reported in one 422.
type request struct {
	pathUUIDs []string
	query     func(q url.Values, in *input, errs *[]httpx.FieldError) url.Values
	body      func(v any, in *input, errs *[]httpx.FieldError) any
}

// middleware validates the workspace path, the path UUIDs, the query and the
// body, then hands the typed input down in the context.
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
			if rq.query != nil {
				if q := rq.query(r.URL.Query(), &in, &fes); q != nil {
					r.URL.RawQuery = q.Encode()
				}
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
				raw, err := wirejson.Marshal(canonical, wirejson.Compact)
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

// readBody is FastAPI's body read for a JSON body parameter: an empty body is
// absent, a JSON (or missing) content type is parsed, any other body is refused.
func readBody(r *http.Request) (any, error) {
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	if len(raw) == 0 {
		return absent{}, nil
	}
	if ct := r.Header.Get("Content-Type"); ct != "" && !jsonContentType(ct) {
		return raw, nil
	}
	if err := httpx.CheckJSONBody(raw); err != nil {
		return nil, err
	}
	return wirejson.Unmarshal(raw)
}

func jsonContentType(ct string) bool {
	media, _, err := mime.ParseMediaType(ct)
	if err != nil {
		media = strings.ToLower(strings.TrimSpace(strings.SplitN(ct, ";", 2)[0]))
	}
	main, sub, _ := strings.Cut(media, "/")
	return main == "application" && (sub == "json" || strings.HasSuffix(sub, "+json"))
}

// model checks the body is an object.
func model(v any, errs *[]httpx.FieldError) (wirejson.Object, bool) {
	switch o := v.(type) {
	case wirejson.Object:
		return o, true
	case absent:
		*errs = append(*errs, httpx.Missing("body"))
	default:
		*errs = append(*errs, httpx.ModelAttributesType("body"))
	}
	return nil, false
}

// reqStr is a required str field.
func reqStr(o wirejson.Object, key string, errs *[]httpx.FieldError) (string, bool) {
	v, ok := o.Get(key)
	if !ok {
		*errs = append(*errs, httpx.Missing("body", key))
		return "", false
	}
	s, ok := v.(string)
	if !ok {
		*errs = append(*errs, httpx.StringType("body", key))
		return "", false
	}
	return s, true
}

// optStr is an optional str field that may be null.
func optStr(o wirejson.Object, key string, errs *[]httpx.FieldError) (*string, bool) {
	v, ok := o.Get(key)
	if !ok || v == nil {
		return nil, true
	}
	s, ok := v.(string)
	if !ok {
		*errs = append(*errs, httpx.StringType("body", key))
		return nil, false
	}
	return &s, true
}

// optDict is an optional dict field: absent is nil, null is an error unless nullable.
func optDict(o wirejson.Object, key string, nullable bool, errs *[]httpx.FieldError) (map[string]any, bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, true
	}
	if v == nil {
		if nullable {
			return nil, true
		}
		*errs = append(*errs, httpx.DictType("body", key))
		return nil, false
	}
	obj, ok := v.(wirejson.Object)
	if !ok {
		*errs = append(*errs, httpx.DictType("body", key))
		return nil, false
	}
	return toMap(obj), true
}

// toMap is the dict a JSON object decodes to, numbers as written.
func toMap(o wirejson.Object) map[string]any {
	out := make(map[string]any, len(o))
	for _, m := range o {
		out[m.Key] = plain(m.Value)
	}
	return out
}

func plain(v any) any {
	switch t := v.(type) {
	case wirejson.Object:
		return toMap(t)
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = plain(x)
		}
		return out
	}
	return v
}

// maxListLimit and the default limit are list_connections' Query bounds.
const (
	maxListLimit     = 1000
	defaultListLimit = 100
)

func last(q url.Values, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

// listQuery is list_connections' query: status and search are optional and
// empty means none; limit and offset are bounded.
func listQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	in.limit, in.offset = defaultListLimit, 0
	if v, ok := last(q, "status"); ok && v != "" {
		in.status = &v
	}
	if v, ok := last(q, "search"); ok && v != "" {
		pattern := "%" + v + "%"
		in.pattern = &pattern
	}
	if v, ok := last(q, "limit"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: maxListLimit, HasLe: true}, "query", "limit")
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
	return url.Values{"limit": {strconv.Itoa(int(in.limit))}, "offset": {strconv.Itoa(int(in.offset))}}
}

// authCreateBody is MCPAuthConfigCreateRequest; the body passes on as validated.
func authCreateBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	name, nameOK := reqStr(o, "name", errs)
	desc, descOK := optStr(o, "description", errs)
	authType, typeOK := reqStr(o, "auth_type", errs)
	config, cfgOK := optDict(o, "config", false, errs)
	creds, credsOK := optDict(o, "credentials", false, errs)
	if !nameOK || !descOK || !typeOK || !cfgOK || !credsOK {
		return nil
	}
	if config == nil {
		config = map[string]any{}
	}
	if creds == nil {
		creds = map[string]any{}
	}
	in.auth = domain.AuthConfigNew{Name: name, Description: desc, AuthType: authType, Config: config, Credentials: creds}
	return o
}

// authUpdateBody is MCPAuthConfigUpdateRequest: every field optional, null is unchanged.
func authUpdateBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	name, nameOK := optStr(o, "name", errs)
	desc, descOK := optStr(o, "description", errs)
	config, cfgOK := optDict(o, "config", true, errs)
	creds, credsOK := optDict(o, "credentials", true, errs)
	if !nameOK || !descOK || !cfgOK || !credsOK {
		return nil
	}
	in.patch = domain.AuthConfigPatch{Name: name, Description: desc, Config: config, Credentials: creds}
	return o
}

// linkBody is OAuthLinkCreateRequest.
func linkBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	inst, instOK := reqUUID(o, "mcp_instance_id", errs)
	access := "workspace"
	acc, accOK := optStrDefault(o, "access_control", &access, errs)
	provider, provOK := optDict(o, "provider_config", false, errs)
	days, daysOK := optDays(o, errs)
	if !instOK || !accOK || !provOK || !daysOK {
		return nil
	}
	if provider == nil {
		provider = map[string]any{}
	}
	in.link = linkNew{instance: inst, access: acc, provider: provider, days: days}
	return o
}

func reqUUID(o wirejson.Object, key string, errs *[]httpx.FieldError) (uuid.UUID, bool) {
	s, ok := reqStr(o, key, errs)
	if !ok {
		return uuid.Nil, false
	}
	id, fe := httpx.ValidateUUID(s, "body", key)
	if fe != nil {
		*errs = append(*errs, *fe)
		return uuid.Nil, false
	}
	return uuid.MustParse(id), true
}

func optStrDefault(o wirejson.Object, key string, def *string, errs *[]httpx.FieldError) (string, bool) {
	s, ok := optStr(o, key, errs)
	if !ok {
		return "", false
	}
	if s == nil {
		return *def, true
	}
	return *s, true
}

// optDays is expires_in_days: an optional int from 1 to 3650.
func optDays(o wirejson.Object, errs *[]httpx.FieldError) (*int, bool) {
	v, ok := o.Get("expires_in_days")
	if !ok || v == nil {
		return nil, true
	}
	var n int64
	switch t := v.(type) {
	case json.Number:
		i, err := t.Int64()
		if err != nil {
			*errs = append(*errs, httpx.IntType("body", "expires_in_days"))
			return nil, false
		}
		n = i
	case wirejson.Float:
		if float64(t) != float64(int64(t)) {
			*errs = append(*errs, httpx.IntFromFloat("body", "expires_in_days"))
			return nil, false
		}
		n = int64(t)
	default:
		*errs = append(*errs, httpx.IntType("body", "expires_in_days"))
		return nil, false
	}
	if n < 1 {
		*errs = append(*errs, httpx.GreaterThanEqual(1, "body", "expires_in_days"))
		return nil, false
	}
	if n > 3650 {
		*errs = append(*errs, httpx.LessThanEqual(3650, "body", "expires_in_days"))
		return nil, false
	}
	d := int(n)
	return &d, true
}
