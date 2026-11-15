package handlers

import (
	"io"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// mountVerify routes verification, tool discovery, validation and the auth
// probe of /mcp-server-instances.
func mountVerify(g group) {
	v := verifyRoutes{g: g}
	with := func(rq request, mws ...func(http.Handler) http.Handler) chi.Router {
		return g.base.With(append(mws, rq.middleware(g.errs))...)
	}
	edit := requires(g.s, g.errs, "edit", "mcp_instance", "instance_id")
	p := httpx.WorkspacePrefix + "/mcp-server-instances"
	id := []string{"instance_id"}

	with(request{body: validateBody}).Post(p+"/validate", http.HandlerFunc(v.validate))
	with(request{body: plainDictBody}).Post(p+"/validate-connection", http.HandlerFunc(v.validateConnection))
	with(request{pathUUIDs: id}, edit).Post(p+"/{instance_id}/verify", http.HandlerFunc(v.verify))
	with(request{pathUUIDs: id}, edit).Post(p+"/{instance_id}/discover-tools", http.HandlerFunc(v.discover))
	with(request{pathUUIDs: id}, edit).Post(p+"/{instance_id}/probe", http.HandlerFunc(v.probe))
}

type verifyRoutes struct{ g group }

func (v verifyRoutes) reply(w http.ResponseWriter, r *http.Request, body any) {
	if err := (response{status: http.StatusOK, body: body}).visit(w); err != nil {
		v.g.errs.Write(w, r, err)
	}
}

func (v verifyRoutes) verify(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	id := uuidOf(chi.URLParam(r, "instance_id"))
	res, err := v.g.s.svc.Verify(r.Context(), c.Workspace, id, true)
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	v.reply(w, r, wirejson.Object{{Key: "instance_id", Value: id.String()}, {Key: "verification", Value: res}})
}

func (v verifyRoutes) discover(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	tools, res, err := v.g.s.svc.DiscoverInstanceTools(r.Context(), c.Workspace, uuidOf(chi.URLParam(r, "instance_id")))
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	if tools == nil {
		tools = []any{}
	}
	v.reply(w, r, wirejson.Object{{Key: "tools", Value: tools}, {Key: "verification", Value: res}})
}

func (v verifyRoutes) probe(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	res, err := v.g.s.svc.Probe(r.Context(), c.Workspace, uuidOf(chi.URLParam(r, "instance_id")))
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	out := wirejson.Object{{Key: "status", Value: res.Status}, {Key: "methods", Value: res.Methods}}
	if res.HasHints {
		out = append(out, wirejson.Member{Key: "hints", Value: res.Hints})
	}
	v.reply(w, r, out)
}

func (v verifyRoutes) validate(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	o, err := canonicalBody(r)
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	kind, _ := o.Get("type")
	switch kind {
	case "url":
		endpoint, _ := o.Get("endpoint_url")
		u, _ := endpoint.(string)
		if u == "" {
			v.reply(w, r, invalid("endpoint_url is required for type=url"))
			return
		}
		raw, _ := o.Get("headers")
		v.reply(w, r, validationJSON(v.g.s.svc.ValidateConnection(r.Context(), c.Workspace, u, stringMap(raw), "")))
	case "docker", "command":
		v.reply(w, r, wirejson.Object{{Key: "valid", Value: true}, {Key: "errors", Value: []any{}}})
	case "bundle":
		v.reply(w, r, invalid("bundle is not a valid MCP server instance type"))
	default:
		v.reply(w, r, invalid("Unknown type: "+kind.(string)))
	}
}

func (v verifyRoutes) validateConnection(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	o, err := canonicalBody(r)
	if err != nil {
		v.g.errs.Write(w, r, err)
		return
	}
	raw, _ := o.Get("url")
	u, _ := raw.(string)
	headers, _ := o.Get("headers")
	serverID := ""
	if sid, ok := o.Get("server_id"); ok {
		if s, ok := sid.(string); ok {
			if parsed, err := uuid.Parse(s); err == nil {
				serverID = parsed.String()
			}
		}
	}
	v.reply(w, r, validationJSON(v.g.s.svc.ValidateConnection(r.Context(), c.Workspace, u, stringMap(headers), serverID)))
}

// canonicalBody is the body the request middleware validated and re-wrote.
func canonicalBody(r *http.Request) (wirejson.Object, error) {
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil, err
	}
	o, _ := v.(wirejson.Object)
	return o, nil
}

func invalid(msg string) wirejson.Object {
	return wirejson.Object{{Key: "valid", Value: false}, {Key: "errors", Value: []string{msg}}}
}

func validationJSON(res service.Validation) wirejson.Object {
	out := wirejson.Object{{Key: "valid", Value: res.Valid}, {Key: "errors", Value: res.Errors}}
	if res.Valid {
		out = append(out, wirejson.Member{Key: "tool_count", Value: len(res.Tools)}, wirejson.Member{Key: "tools", Value: res.Tools})
	}
	if res.AuthMethods != nil {
		out = append(out, wirejson.Member{Key: "auth_methods", Value: res.AuthMethods})
	}
	return out
}

// stringMap is a headers object's string values.
func stringMap(v any) map[string]string {
	o, ok := v.(wirejson.Object)
	if !ok {
		return nil
	}
	out := map[string]string{}
	for _, m := range o {
		if s, ok := m.Value.(string); ok {
			out[m.Key] = s
		}
	}
	return out
}

// validateBody is ValidateRequest.
func validateBody(v any, _ *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	name, _ := optStr(o, "name", errs)
	kind, _ := reqStr(o, "type", errs)
	endpoint, _ := optStr(o, "endpoint_url", errs)
	headers := wirejson.Object{}
	if raw, has := o.Get("headers"); has {
		h, isObj := raw.(wirejson.Object)
		if !isObj {
			*errs = append(*errs, httpx.DictType("body", "headers"))
		}
		for _, m := range h {
			if _, isStr := m.Value.(string); !isStr {
				*errs = append(*errs, httpx.StringType("body", "headers", m.Key))
			}
		}
		if isObj {
			headers = h
		}
	}
	return wirejson.Object{{Key: "name", Value: orNil(name)}, {Key: "type", Value: kind},
		{Key: "endpoint_url", Value: orNil(endpoint)}, {Key: "headers", Value: headers}}
}

// plainDictBody is a `data: dict[str, Any]` body.
func plainDictBody(v any, _ *input, errs *[]httpx.FieldError) any {
	o, ok := v.(wirejson.Object)
	if !ok {
		if _, isAbsent := v.(absent); isAbsent {
			*errs = append(*errs, httpx.Missing("body"))
		} else {
			*errs = append(*errs, httpx.DictType("body"))
		}
		return nil
	}
	return o
}
