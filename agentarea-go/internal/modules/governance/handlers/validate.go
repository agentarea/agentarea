package handlers

import (
	"context"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// input is what a route's parameters and body validated to, kept in the
// request context for the strict handler: the generated binding cannot tell
// an absent key from null, nor report pydantic's errors.
type input struct {
	path map[string]string
	ruleList
	ruleCreate
	rulePatch
	preview
	auditList
	secretBody
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

// request is one route's admission and parameters. admin runs first when
// the route declares requires_workspace_admin (a dependency, before
// FastAPI validates anything); then path UUIDs, query and body, every error
// in one 422.
type request struct {
	admin     bool
	pathUUIDs []string
	query     func(q url.Values, in *input, errs *[]httpx.FieldError)
	body      func(v any, in *input, errs *[]httpx.FieldError)
}

func (rq request) middleware(errs *httpx.Errors, admin func(context.Context) error) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if rq.admin {
				if err := admin(r.Context()); err != nil {
					errs.Write(w, r, err)
					return
				}
			}
			var fes []httpx.FieldError
			in := input{path: map[string]string{}}
			if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
				fes = append(fes, *fe)
			}
			for _, name := range rq.pathUUIDs {
				id, fe := httpx.ValidateUUID(chi.URLParam(r, name), "path", name)
				if fe != nil {
					fes = append(fes, *fe)
					continue
				}
				in.path[name] = id
			}
			if rq.query != nil {
				rq.query(httpx.Query(r.URL.RawQuery), &in, &fes)
			}
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
			r.URL.RawQuery = ""
			if rq.body != nil {
				r.Body = io.NopCloser(strings.NewReader("{}"))
				r.ContentLength = 2
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

// absent is a request body FastAPI saw none of.
type absent struct{}

// readBody is FastAPI's body read for a JSON body parameter: an empty body
// is absent, a JSON (or missing) content type is parsed, any other body is
// raw bytes the model then refuses.
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

// model checks the body is an object; loc is ("body",).
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

func body(k ...any) []any { return append([]any{"body"}, k...) }
