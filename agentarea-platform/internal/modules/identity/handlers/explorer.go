package handlers

import (
	"net/http"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/service"
)

func (s *Server) sync(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	n, err := s.svc.SyncMembers(r.Context(), c)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, wirejson.Object{{Key: "written", Value: n}, {Key: "collections", Value: 0}})
}

func (s *Server) graph(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	g, err := s.svc.AccessGraph(r.Context(), c)
	if err != nil {
		return err
	}
	nodes := make([]any, 0, len(g.Nodes))
	for _, n := range g.Nodes {
		var count any
		if n.Count != nil {
			count = *n.Count
		}
		nodes = append(nodes, wirejson.Object{
			{Key: "id", Value: n.ID}, {Key: "kind", Value: n.Kind}, {Key: "name", Value: n.Name},
			{Key: "subtitle", Value: n.Subtitle}, {Key: "color", Value: n.Color}, {Key: "count", Value: count},
		})
	}
	edges := make([]any, 0, len(g.Edges))
	for _, e := range g.Edges {
		edges = append(edges, wirejson.Object{{Key: "from", Value: e.From}, {Key: "to", Value: e.To}, {Key: "relation", Value: e.Relation}})
	}
	return writeJSON(w, http.StatusOK, wirejson.Object{
		{Key: "enabled", Value: true},
		{Key: "nodes", Value: nodes},
		{Key: "edges", Value: edges},
		{Key: "stats", Value: wirejson.Object{
			{Key: "governed_skill_count", Value: g.Stats.GovernedSkillCount},
			{Key: "rule_count", Value: g.Stats.RuleCount},
			{Key: "direct_exception_count", Value: g.Stats.DirectExceptionCount},
		}},
	})
}

func (s *Server) relationships(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	var namespace *string
	if vs := httpx.Query(r.URL.RawQuery)["namespace"]; len(vs) > 0 {
		namespace = &vs[len(vs)-1]
	}
	items, err := s.svc.Relationships(r.Context(), c, namespace)
	if err != nil {
		return err
	}
	list := make([]any, 0, len(items))
	for _, it := range items {
		var fanout any
		if it.Fanout != nil {
			fanout = *it.Fanout
		}
		list = append(list, wirejson.Object{
			{Key: "namespace", Value: it.Namespace}, {Key: "object", Value: it.Object},
			{Key: "object_name", Value: it.ObjectName}, {Key: "relation", Value: it.Relation},
			{Key: "subject", Value: it.Subject}, {Key: "subject_kind", Value: it.SubjectKind},
			{Key: "subject_name", Value: it.SubjectName}, {Key: "fanout", Value: fanout},
			{Key: "direct", Value: it.Direct},
		})
	}
	return writeJSON(w, http.StatusOK, wirejson.Object{{Key: "relationships", Value: list}, {Key: "count", Value: len(list)}})
}

// nestedStr is a required str field of a nested model at loc.
func nestedStr(o wirejson.Object, key string, errs *[]httpx.FieldError, loc ...any) string {
	at := append(append([]any{}, loc...), key)
	v, ok := o.Get(key)
	if !ok {
		*errs = append(*errs, httpx.Missing(at...))
		return ""
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.StringType(at...))
	}
	return s
}

// writeBody is RelationshipWriteRequest.
func writeBody(r *http.Request) (service.RelationshipWrite, error) {
	var out service.RelationshipWrite
	err := body(r, func(o wirejson.Object, errs *[]httpx.FieldError) {
		out.Namespace = requiredStr(o, "namespace", errs)
		out.Object = requiredStr(o, "object", errs)
		out.Relation = requiredStr(o, "relation", errs)
		out.SubjectID, _ = str(o, "subject_id", 0, 0, true, errs)
		v, ok := o.Get("subject_set")
		if !ok || v == nil {
			return
		}
		set, isObj := v.(wirejson.Object)
		if !isObj {
			*errs = append(*errs, httpx.ModelAttributesType("body", "subject_set"))
			return
		}
		out.SubjectSet = &service.SubjectSet{
			Namespace: nestedStr(set, "namespace", errs, "body", "subject_set"),
			Object:    nestedStr(set, "object", errs, "body", "subject_set"),
			Relation:  nestedStr(set, "relation", errs, "body", "subject_set"),
		}
	})
	return out, err
}

func (s *Server) grant(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	req, err := writeBody(r)
	if err != nil {
		return err
	}
	if err := s.svc.GrantRelationship(r.Context(), c, req); err != nil {
		return err
	}
	return writeJSON(w, http.StatusCreated, wirejson.Object{{Key: "ok", Value: true}})
}

func (s *Server) revokeGrant(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	req, err := writeBody(r)
	if err != nil {
		return err
	}
	if err := s.svc.RevokeRelationship(r.Context(), c, req); err != nil {
		return err
	}
	return noContent(w)
}

func (s *Server) check(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	var ns, object, relation, subject string
	err = body(r, func(o wirejson.Object, errs *[]httpx.FieldError) {
		ns = requiredStr(o, "namespace", errs)
		object = requiredStr(o, "object", errs)
		relation = requiredStr(o, "relation", errs)
		subject = requiredStr(o, "subject_id", errs)
	})
	if err != nil {
		return err
	}
	allowed, err := s.svc.CheckPermission(r.Context(), c, ns, object, relation, subject)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, wirejson.Object{{Key: "allowed", Value: allowed}})
}

// ResourceKinds are ResolveRequest.resource_kind's choices.
func ResourceKinds() []string { return []string{"skill", "collection", "mcp", "agent"} }

func (s *Server) resolve(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	var subject, kind, resource string
	err = body(r, func(o wirejson.Object, errs *[]httpx.FieldError) {
		subject = requiredStr(o, "subject_id", errs)
		v, ok := o.Get("resource_kind")
		if !ok {
			*errs = append(*errs, httpx.Missing("body", "resource_kind"))
		} else if k, isStr := v.(string); !isStr || !contains(ResourceKinds(), k) {
			*errs = append(*errs, httpx.LiteralError(ResourceKinds(), "body", "resource_kind"))
		} else {
			kind = k
		}
		resource = requiredStr(o, "resource_id", errs)
	})
	if err != nil {
		return err
	}
	res, err := s.svc.ResolveAccess(r.Context(), c, subject, kind, resource)
	if err != nil {
		return err
	}
	paths := make([]any, 0, len(res.Paths))
	for _, p := range res.Paths {
		hops := make([]any, 0, len(p.Hops))
		for _, h := range p.Hops {
			hops = append(hops, wirejson.Object{{Key: "id", Value: h.ID}, {Key: "name", Value: h.Name}, {Key: "kind", Value: h.Kind}, {Key: "color", Value: h.Color}})
		}
		rels := make([]any, 0, len(p.Rels))
		for _, rel := range p.Rels {
			rels = append(rels, rel)
		}
		paths = append(paths, wirejson.Object{{Key: "relation", Value: p.Relation}, {Key: "hops", Value: hops}, {Key: "rels", Value: rels}})
	}
	return writeJSON(w, http.StatusOK, wirejson.Object{
		{Key: "allowed", Value: res.Allowed},
		{Key: "effective_relation", Value: strOrNil(res.EffectiveRelation)},
		{Key: "verb", Value: res.Verb},
		{Key: "paths", Value: paths},
	})
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
