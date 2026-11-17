package handlers

import (
	"bytes"
	"context"
	"io"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// input is what a route's parameters and body validated to, kept in the
// request context for the strict handler.
type input struct {
	create  service.Create
	patch   service.Patch
	collect collectionInput
	// area is what another route group's parse functions validated to.
	area any
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

// request is one route's parameters: path UUIDs, then query, then body.
type request struct {
	pathUUIDs []string
	query     func(q map[string][]string, in *input, errs *[]httpx.FieldError)
	body      func(v any, in *input, errs *[]httpx.FieldError)
	// optionalBody admits a missing body.
	optionalBody bool
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
			if rq.query != nil {
				rq.query(r.URL.Query(), &in, &fes)
			}
			if rq.body != nil {
				v, err := readBody(r)
				if err != nil {
					errs.Write(w, r, err)
					return
				}
				if _, empty := v.(absent); empty && rq.optionalBody {
					v = wirejson.Object{}
				}
				rq.body(v, &in, &fes)
			}
			if err := httpx.Validation(fes...); err != nil {
				errs.Write(w, r, err)
				return
			}
			if rq.body != nil {
				r.Body = io.NopCloser(bytes.NewReader([]byte("{}")))
				r.ContentLength = 2
				r.Header.Set("Content-Type", "application/json")
			}
			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), inputKey{}, in)))
		})
	}
}
