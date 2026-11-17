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

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// input is what a route's parameters and body validated to, kept in the
// request context for the strict handler: the generated binding cannot tell
// an absent key from null, nor report pydantic's errors.
type input struct {
	create        domain.New
	patch         domain.Patch
	association   string
	uploads       []sandboxapi.UploadEntry
	limit, offset int32
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

// request is one route's parameters: path UUIDs, then query, then body, in
// FastAPI's order; every error is reported in one 422.
type request struct {
	pathUUIDs []string
	query     func(q url.Values, in *input, errs *[]httpx.FieldError) url.Values
	body      func(v any, in *input, errs *[]httpx.FieldError) any
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

// MaxListLimit and the default limit are list_projects' Query bounds.
const (
	MaxListLimit     = 1000
	DefaultListLimit = 100
)

func last(q url.Values, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

func listQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	in.limit, in.offset = DefaultListLimit, 0
	if v, ok := last(q, "limit"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: MaxListLimit, HasLe: true}, "query", "limit")
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

func projectFields() []string {
	return []string{"name", "description", "instructions", "parent_project_id"}
}

// MaxName and friends are the DTO's Field bounds (schemas/dto.py).
const (
	MaxName         = 255
	MaxDescription  = 1000
	MaxInstructions = 20000
)

// createBody is ProjectCreate (extra="forbid", name stripped).
func createBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
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
		in.create.Name = stripped
	}
	in.create.Description, _ = str(o, "description", 0, MaxDescription, true, errs)
	in.create.Instructions, _ = str(o, "instructions", 0, MaxInstructions, true, errs)
	in.create.ParentProjectID, _ = uuidField(o, "parent_project_id", errs)
	extraForbidden(o, projectFields(), errs)
	return map[string]any{
		"name": in.create.Name, "description": in.create.Description,
		"instructions": in.create.Instructions, "parent_project_id": in.create.ParentProjectID,
	}
}

// updateBody is ProjectUpdate: only sent keys are written; name may be
// left out but not set to null, and is not stripped.
func updateBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	if raw, present := o.Get("name"); present && raw == nil {
		*errs = append(*errs, httpx.ValueError("may be omitted, but not set to null", "body", "name"))
	} else {
		in.patch.Name, _ = str(o, "name", 1, MaxName, false, errs)
	}
	in.patch.Description.Value, in.patch.Description.Set = str(o, "description", 0, MaxDescription, true, errs)
	in.patch.Instructions.Value, in.patch.Instructions.Set = str(o, "instructions", 0, MaxInstructions, true, errs)
	in.patch.ParentProjectID.Value, in.patch.ParentProjectID.Set = uuidField(o, "parent_project_id", errs)
	extraForbidden(o, projectFields(), errs)
	out := map[string]any{}
	if in.patch.Name != nil {
		out["name"] = *in.patch.Name
	}
	if in.patch.Description.Set {
		out["description"] = in.patch.Description.Value
	}
	if in.patch.Instructions.Set {
		out["instructions"] = in.patch.Instructions.Value
	}
	if in.patch.ParentProjectID.Set {
		out["parent_project_id"] = in.patch.ParentProjectID.Value
	}
	return out
}

// associationBody is AssociationBody{id: str}; other keys are ignored.
func associationBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	id, set := str(o, "id", 0, 0, false, errs)
	switch {
	case !set:
		*errs = append(*errs, httpx.Missing("body", "id"))
	case id != nil:
		in.association = *id
	}
	return map[string]any{"id": in.association}
}
