package handlers

import (
	"net/http"
	"net/url"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// maxSpecIDs is the ids Query's max_length.
const maxSpecIDs = 100

// specInput is an /mcp-servers route's parameters and body, validated.
type specInput struct {
	query    catalogapi.MCPSpecQuery
	page     int
	pageSize int
	create   catalogapi.MCPSpecNew
	patch    service.SpecPatch
}

// mountSpecs routes /mcp-servers, the workspace's MCP server specs, when
// catalog's specs are wired; each route checks the caller's relation on the
// spec once it is resolved.
func mountSpecs(g group) {
	if !g.s.svc.InstancePorts().Specs {
		return
	}
	r := specRoutes{g: g}
	with := func(rq request) chi.Router { return g.base.With(rq.middleware(g.errs)) }
	p := httpx.WorkspacePrefix + "/mcp-servers"
	with(request{body: specCreateBody}).Post(p+"/", http.HandlerFunc(r.create))
	with(request{query: specListQuery}).Get(p+"/", http.HandlerFunc(r.list))
	with(request{}).Get(p+"/{server_id}", http.HandlerFunc(r.get))
	with(request{body: specUpdateBody}).Patch(p+"/{server_id}", http.HandlerFunc(r.update))
	with(request{}).Delete(p+"/{server_id}", http.HandlerFunc(r.delete))
	with(request{}).Post(p+"/{server_id}/deploy", http.HandlerFunc(r.deploy))
}

func specListQuery(q url.Values, in *input, errs *[]httpx.FieldError) url.Values {
	sq := &in.spec
	sq.page, sq.pageSize = 1, httpx.DefaultPageSize
	if v, ok := lastValue(q, "status"); ok {
		sq.query.Status = &v
	}
	if v, ok := lastValue(q, "is_public"); ok {
		if b, valid := httpx.ParseBool(v); valid {
			sq.query.IsPublic = &b
		} else {
			*errs = append(*errs, httpx.BoolParsing("query", "is_public"))
		}
	}
	if v, ok := lastValue(q, "tag"); ok {
		sq.query.Tag = &v
	}
	if ids, ok := q["ids"]; ok {
		if len(ids) > maxSpecIDs {
			*errs = append(*errs, listTooLong(maxSpecIDs, len(ids), "query", "ids"))
		}
		sq.query.SpecIDs = []string{}
		for i, raw := range ids {
			id, fe := httpx.ValidateUUID(raw, "query", "ids", i)
			if fe != nil {
				*errs = append(*errs, *fe)
				continue
			}
			sq.query.SpecIDs = append(sq.query.SpecIDs, id)
		}
	}
	if v, ok := lastValue(q, "page"); ok {
		if n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: httpx.MaxPage, HasLe: true}, "query", "page"); fe != nil {
			*errs = append(*errs, *fe)
		} else {
			sq.page = int(n)
		}
	}
	if v, ok := lastValue(q, "page_size"); ok {
		if n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: httpx.MaxPageSize, HasLe: true}, "query", "page_size"); fe != nil {
			*errs = append(*errs, *fe)
		} else {
			sq.pageSize = int(n)
		}
	}
	if v, ok := lastValue(q, "search"); ok {
		sq.query.Search = &v
	}
	return nil
}

func lastValue(q url.Values, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

// specCreateBody is MCPServerCreate.
func specCreateBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	in.spec.create = serverCreate(fields{o: o, base: []any{"body"}, errs: errs})
	return o
}

// specUpdateBody is MCPServerUpdate: unset is unchanged, and a NOT NULL
// column may be left out but not set to null.
func specUpdateBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	f := fields{o: o, base: []any{"body"}, errs: errs}
	p := service.SpecPatch{Set: map[string]bool{}}
	notNull := func(key string) bool {
		val, has := o.Get(key)
		if !has {
			return false
		}
		if val == nil {
			f.add(httpx.ValueError("may be omitted, but not set to null", f.loc(key)...))
			return false
		}
		return true
	}
	if notNull("name") {
		if s, good := f.name(false); good && s != nil {
			p.Name, p.Set["name"] = *s, true
		}
	}
	for _, key := range []string{"description", "version", "status"} {
		if notNull(key) {
			if s, good := f.str(key, false, false, 0, 0); good && s != nil {
				p.Set[key] = true
				switch key {
				case "description":
					p.Description = *s
				case "version":
					p.Version = *s
				default:
					p.Status = *s
				}
			}
		}
	}
	if _, has := o.Get("docker_image_url"); has {
		if img, good := f.str("docker_image_url", false, true, 0, 0); good {
			if img != nil {
				if msg := domain.ImageReferenceError(*img); msg != "" {
					f.add(httpx.ValueError(msg, f.loc("docker_image_url")...))
				}
			}
			p.DockerImageURL, p.Set["docker_image_url"] = img, true
		}
	}
	for _, key := range []string{"remote_url", "registry_url"} {
		if _, has := o.Get(key); has {
			if s, good := f.str(key, false, true, 0, 0); good {
				p.Set[key] = true
				if key == "remote_url" {
					p.RemoteURL = s
				} else {
					p.RegistryURL = s
				}
			}
		}
	}
	if notNull("tags") {
		if l, good := f.strList("tags", false); good {
			p.Tags, p.Set["tags"] = l, true
		}
	}
	if notNull("is_public") {
		if b, good := f.boolean("is_public"); good {
			p.IsPublic, p.Set["is_public"] = b, true
		}
	}
	if notNull("env_schema") {
		if l, good := f.dictList("env_schema"); good {
			p.EnvSchema, p.Set["env_schema"] = l, true
		}
	}
	if _, has := o.Get("cmd"); has {
		if l, good := f.strList("cmd", true); good {
			p.Cmd, p.Set["cmd"] = l, true
		}
	}
	if _, has := o.Get("json_spec"); has {
		if spec, good := f.dict("json_spec", false, true); good && (spec == nil || f.specCheck("json_spec", spec, domain.ServerSpec)) {
			p.JSONSpec, p.Set["json_spec"] = spec, true
		}
	}
	f.extra("name", "description", "docker_image_url", "remote_url", "version", "tags", "is_public", "status",
		"env_schema", "cmd", "json_spec", "registry_url")
	in.spec.patch = p
	return o
}

type specRoutes struct{ g group }

func (s specRoutes) reply(w http.ResponseWriter, r *http.Request, body any) {
	if err := (response{status: http.StatusOK, body: body}).visit(w); err != nil {
		s.g.errs.Write(w, r, err)
	}
}

func (s specRoutes) create(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err == nil {
		var sp catalogapi.MCPSpec
		if sp, err = s.g.s.svc.CreateSpec(r.Context(), c, inputFrom(r.Context()).spec.create); err == nil {
			s.reply(w, r, specJSON(sp))
			return
		}
	}
	s.g.errs.Write(w, r, err)
}

func (s specRoutes) list(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err != nil {
		s.g.errs.Write(w, r, err)
		return
	}
	in := inputFrom(r.Context()).spec
	page, size := in.page, in.pageSize
	if in.query.SpecIDs != nil {
		page, size = 1, len(in.query.SpecIDs)
	}
	q := in.query
	q.Limit, q.Offset = size, (page-1)*size
	specs, total, err := s.g.s.svc.ListSpecs(r.Context(), c, q)
	if err != nil {
		s.g.errs.Write(w, r, err)
		return
	}
	items := make([]any, len(specs))
	for i, sp := range specs {
		items[i] = specJSON(sp)
	}
	s.reply(w, r, wirejson.Object{
		{Key: "items", Value: items}, {Key: "total", Value: total}, {Key: "page", Value: page},
		{Key: "page_size", Value: size}, {Key: "has_next", Value: q.Offset+size < total},
	})
}

func (s specRoutes) get(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err == nil {
		var sp catalogapi.MCPSpec
		if sp, err = s.g.s.svc.GetSpec(r.Context(), c, chi.URLParam(r, "server_id")); err == nil {
			s.reply(w, r, specJSON(sp))
			return
		}
	}
	s.g.errs.Write(w, r, err)
}

func (s specRoutes) update(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err == nil {
		var sp catalogapi.MCPSpec
		if sp, err = s.g.s.svc.UpdateSpec(r.Context(), c, chi.URLParam(r, "server_id"), inputFrom(r.Context()).spec.patch); err == nil {
			s.reply(w, r, specJSON(sp))
			return
		}
	}
	s.g.errs.Write(w, r, err)
}

func (s specRoutes) delete(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err == nil {
		if err = s.g.s.svc.DeleteSpec(r.Context(), c, chi.URLParam(r, "server_id")); err == nil {
			s.reply(w, r, wirejson.Object{{Key: "status", Value: "success"}})
			return
		}
	}
	s.g.errs.Write(w, r, err)
}

func (s specRoutes) deploy(w http.ResponseWriter, r *http.Request) {
	c, err := caller(r.Context())
	if err == nil {
		var sp catalogapi.MCPSpec
		if sp, err = s.g.s.svc.DeploySpec(r.Context(), c, chi.URLParam(r, "server_id")); err == nil {
			s.reply(w, r, wirejson.Object{{Key: "status", Value: "success"},
				{Key: "message", Value: "MCP server " + sp.Name + " deployed successfully"}})
			return
		}
	}
	s.g.errs.Write(w, r, err)
}

// holdsPlatformAddress is _holds_platform_address: a platform spec that is no
// catalog mirror backs a platform-managed connection, and where it runs is
// the deployment's topology.
func holdsPlatformAddress(sp catalogapi.MCPSpec) bool {
	return sp.WorkspaceID == "platform" && sp.RegistryItemID == nil
}

// specJSON is MCPServerResponse.
func specJSON(sp catalogapi.MCPSpec) wirejson.Object {
	remote := orNil(sp.RemoteURL)
	var jsonSpec any
	if sp.JSONSpec != nil {
		jsonSpec = sp.JSONSpec
	}
	if holdsPlatformAddress(sp) {
		remote = nil
		if remotes, ok := sp.JSONSpec["remotes"].([]any); ok {
			spec := make(map[string]any, len(sp.JSONSpec))
			for k, v := range sp.JSONSpec {
				spec[k] = v
			}
			hidden := make([]any, len(remotes))
			for i, rm := range remotes {
				if m, ok := rm.(map[string]any); ok {
					cp := make(map[string]any, len(m))
					for k, v := range m {
						if k != "url" {
							cp[k] = v
						}
					}
					rm = cp
				}
				hidden[i] = rm
			}
			spec["remotes"] = hidden
			jsonSpec = spec
		}
	}
	tags, env := sp.Tags, sp.EnvSchema
	if tags == nil {
		tags = []any{}
	}
	if env == nil {
		env = []any{}
	}
	var cmd any
	if sp.Cmd != nil {
		cmd = sp.Cmd
	}
	return wirejson.Object{
		{Key: "id", Value: sp.ID},
		{Key: "slug", Value: sp.Slug},
		{Key: "name", Value: sp.Name},
		{Key: "description", Value: sp.Description},
		{Key: "docker_image_url", Value: orNil(sp.DockerImageURL)},
		{Key: "version", Value: sp.Version},
		{Key: "tags", Value: tags},
		{Key: "is_public", Value: sp.IsPublic},
		{Key: "env_schema", Value: env},
		{Key: "cmd", Value: cmd},
		{Key: "remote_url", Value: remote},
		{Key: "json_spec", Value: jsonSpec},
		{Key: "registry_url", Value: orNil(sp.RegistryURL)},
		{Key: "registry_item_id", Value: orNil(sp.RegistryItemID)},
		{Key: "status", Value: sp.Status},
		{Key: "created_at", Value: utcISO(sp.CreatedAt)},
		{Key: "updated_at", Value: utcISO(sp.UpdatedAt)},
	}
}
