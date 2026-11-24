package service

import (
	"context"
	"errors"
	"slices"
	"strconv"
	"strings"
	"sync"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// GraphReadConcurrency bounds the explorer's per-object reads.
const GraphReadConcurrency = 16

// ErrNoResources: the explorer route needs reads no module provides yet.
var ErrNoResources = errors.New("access explorer needs the agents and connections reads, which are not wired")

// GraphNode, GraphEdge and GraphStats are the explorer's graph.
type GraphNode struct {
	ID, Kind, Name, Subtitle, Color string
	Count                           *int
}

type GraphEdge struct{ From, To, Relation string }

type GraphStats struct{ GovernedSkillCount, RuleCount, DirectExceptionCount int }

type Graph struct {
	Nodes []GraphNode
	Edges []GraphEdge
	Stats GraphStats
}

// Relationship is RelationshipItem.
type Relationship struct {
	Namespace, Object, ObjectName, Relation, Subject, SubjectKind, SubjectName string
	Fanout                                                                     *int
	Direct                                                                     bool
}

// SubjectSet is a group subject, which the explorer refuses.
type SubjectSet struct{ Namespace, Object, Relation string }

// RelationshipWrite is RelationshipWriteRequest.
type RelationshipWrite struct {
	Namespace, Object, Relation string
	SubjectID                   *string
	SubjectSet                  *SubjectSet
}

// ResolveHop, ResolvePath and Resolution are ResolveResponse.
type ResolveHop struct{ ID, Name, Kind, Color string }

type ResolvePath struct {
	Relation string
	Hops     []ResolveHop
	Rels     []string
}

type Resolution struct {
	Allowed           bool
	EffectiveRelation *string
	Verb              string
	Paths             []ResolvePath
}

func refusal(status int, detail string) error { return &domain.Refusal{Status: status, Detail: detail} }

func graphError(err error) bool {
	var resp *authz.ResponseError
	var down *authz.UnavailableError
	return errors.As(err, &resp) || errors.As(err, &down)
}

func (s *Service) resources() (Resources, error) {
	if s.d.Resources == nil {
		return nil, ErrNoResources
	}
	return s.d.Resources, nil
}

// resourceTuples is _resource_tuples: the grants on each object, read one
// object at a time; a graph outage reads as no grants.
func (s *Service) resourceTuples(ctx context.Context, objectIDs []string) ([]authz.Tuple, error) {
	ids := slices.Clone(objectIDs)
	slices.Sort(ids)
	ids = slices.Compact(ids)
	batches := make([][]authz.Tuple, len(ids))
	errs := make([]error, len(ids))
	sem := make(chan struct{}, GraphReadConcurrency)
	var wg sync.WaitGroup
	for i, id := range ids {
		wg.Go(func() {
			sem <- struct{}{}
			defer func() { <-sem }()
			batches[i], errs[i] = s.d.Reader.Read(ctx, authz.Query{Type: authz.TypeResource, ID: id})
		})
	}
	wg.Wait()
	if err := errors.Join(errs...); err != nil {
		if !graphError(err) {
			return nil, err
		}
		s.log.ErrorContext(ctx, "Failed to query resource relationships from graph backend", "error", err)
		return []authz.Tuple{}, nil
	}
	var out []authz.Tuple
	for _, b := range batches {
		out = append(out, b...)
	}
	return out, nil
}

// subjectOf is the tuple's subject_id: none for a userset.
func subjectOf(t authz.Tuple) string {
	if strings.Contains(t.User, "#") {
		return ""
	}
	return t.User
}

func agentOf(subject string) (string, bool) { return strings.CutPrefix(subject, authz.TypeAgent+":") }

// explorerMemberIDs is _workspace_member_ids: membership rows, the caller
// and the owner.
func (s *Service) explorerMemberIDs(ctx context.Context, c authn.Caller) (map[string]bool, error) {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	rows, err := s.d.Store.MembershipUserIDs(ctx, q, c.Workspace.ID())
	if err != nil {
		return nil, err
	}
	w, ok, err := s.d.Store.GetWorkspace(ctx, q, c.Workspace.ID())
	if err != nil {
		return nil, err
	}
	out := map[string]bool{c.UserID: true}
	for _, id := range rows {
		out[id] = true
	}
	if ok && w.OwnerUserID != "" {
		out[w.OwnerUserID] = true
	}
	return out, nil
}

// assertObject is _assert_object_in_workspace.
func (s *Service) assertObject(ctx context.Context, c authn.Caller, namespace, objectID string) error {
	res, err := s.resources()
	if err != nil {
		return err
	}
	if !domain.ReadableNamespace(namespace) {
		return refusal(422, "Unsupported namespace: "+domain.PyRepr(namespace))
	}
	parsed, ok := PyUUID(objectID)
	if !ok {
		return refusal(422, "Invalid object id: "+domain.PyRepr(objectID))
	}
	found, err := res.Exists(ctx, c.Workspace, namespace, uuid.MustParse(parsed))
	if err != nil {
		return err
	}
	if !found {
		return refusal(403, namespace+":"+objectID+" not found in your workspace")
	}
	return nil
}

// assertSubject is _assert_subject_in_workspace.
func (s *Service) assertSubject(ctx context.Context, c authn.Caller, subject string) error {
	if id, ok := agentOf(subject); ok {
		return s.assertObject(ctx, c, domain.NamespaceAgent, id)
	}
	if id, ok := strings.CutPrefix(subject, authz.TypeUser+":"); ok {
		members, err := s.explorerMemberIDs(ctx, c)
		if err != nil {
			return err
		}
		if !members[id] {
			return refusal(403, "Subject user is not in your workspace")
		}
		return nil
	}
	return refusal(422, "Unsupported subject: "+domain.PyRepr(subject))
}

// toGrant is _to_resource_grant.
func toGrant(w RelationshipWrite) (authz.Tuple, error) {
	if w.SubjectSet != nil {
		return authz.Tuple{}, refusal(422, "Group (subject_set) grants are managed via project/role, not the explorer")
	}
	if w.SubjectID == nil {
		return authz.Tuple{}, refusal(422, "subject_id is required")
	}
	grant, ok := domain.LegacyRelationToGrant(w.Relation)
	if !ok {
		return authz.Tuple{}, refusal(422, "Unsupported relation for a resource grant: "+domain.PyRepr(w.Relation))
	}
	return authz.Tuple{User: *w.SubjectID, Relation: grant, Object: authz.ObjectRef(authz.TypeResource, w.Object)}, nil
}

// AccessGraph is get_graph for an admin.
func (s *Service) AccessGraph(ctx context.Context, c authn.Caller) (Graph, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return Graph{}, err
	}
	res, err := s.resources()
	if err != nil {
		return Graph{}, err
	}
	agents, err := res.Agents(ctx, c.Workspace, false)
	if err != nil {
		return Graph{}, err
	}
	collections, err := res.Collections(ctx, c.Workspace)
	if err != nil {
		return Graph{}, err
	}
	servers, err := res.MCPServers(ctx, c.Workspace)
	if err != nil {
		return Graph{}, err
	}
	counts, err := res.SkillCounts(ctx, c.Workspace)
	if err != nil {
		return Graph{}, err
	}
	skills, err := res.Skills(ctx, c.Workspace)
	if err != nil {
		return Graph{}, err
	}
	skillIDs := map[string]bool{}
	for _, sk := range skills {
		skillIDs[sk.ID] = true
	}
	g := Graph{Nodes: []GraphNode{}, Edges: []GraphEdge{}}
	g.Stats.GovernedSkillCount = len(skillIDs)
	agentIDs := map[string]bool{}
	nodeByUUID := map[string]string{}
	for i, a := range agents {
		id := domain.NamespaceAgent + ":" + a.ID
		g.Nodes = append(g.Nodes, GraphNode{ID: id, Kind: domain.KindAgent, Name: a.Name, Subtitle: "agent", Color: domain.Color(domain.KindAgent, i)})
		agentIDs[a.ID], nodeByUUID[a.ID] = true, id
	}
	for i, col := range collections {
		n := counts[col.ID]
		id := domain.NamespaceSkillCollection + ":" + col.ID
		g.Nodes = append(g.Nodes, GraphNode{ID: id, Kind: domain.KindCollection, Name: col.Name, Subtitle: strconv.Itoa(n) + " skills", Color: domain.Color(domain.KindCollection, i), Count: &n})
		nodeByUUID[col.ID] = id
	}
	for i, m := range servers {
		id := domain.NamespaceMCPServer + ":" + m.ID
		g.Nodes = append(g.Nodes, GraphNode{ID: id, Kind: domain.KindMCP, Name: m.Name, Subtitle: "MCP server", Color: domain.Color(domain.KindMCP, i)})
		nodeByUUID[m.ID] = id
	}
	objects := make([]string, 0, len(nodeByUUID)+len(skillIDs))
	for id := range nodeByUUID {
		objects = append(objects, id)
	}
	for id := range skillIDs {
		objects = append(objects, id)
	}
	tuples, err := s.resourceTuples(ctx, objects)
	if err != nil {
		return Graph{}, err
	}
	for _, t := range tuples {
		label, ok := domain.GrantLabel(t.Relation)
		if !ok {
			continue
		}
		obj := t.ObjectID()
		agent, isAgent := agentOf(subjectOf(t))
		known := isAgent && agentIDs[agent]
		if skillIDs[obj] && known {
			g.Stats.DirectExceptionCount++
		}
		target, ok := nodeByUUID[obj]
		if !ok {
			continue
		}
		g.Stats.RuleCount++
		if known && domain.NamespaceAgent+":"+agent != target {
			g.Edges = append(g.Edges, GraphEdge{From: domain.NamespaceAgent + ":" + agent, To: target, Relation: label})
		}
	}
	return g, nil
}

// Relationships is list_relationships for an admin; namespace narrows to
// one entity kind.
func (s *Service) Relationships(ctx context.Context, c authn.Caller, namespace *string) ([]Relationship, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return nil, err
	}
	if namespace != nil && !domain.ReadableNamespace(*namespace) {
		return nil, refusal(422, "Unsupported namespace: "+domain.PyRepr(*namespace))
	}
	res, err := s.resources()
	if err != nil {
		return nil, err
	}
	names := func(list []Named, err error) (map[string]string, []string, error) {
		m := map[string]string{}
		order := []string{}
		for _, n := range list {
			if _, seen := m[n.ID]; !seen {
				order = append(order, n.ID)
			}
			m[n.ID] = n.Name
		}
		return m, order, err
	}
	agentNames, agentOrder, err := names(res.Agents(ctx, c.Workspace, true))
	if err != nil {
		return nil, err
	}
	collectionNames, collectionOrder, err := names(res.Collections(ctx, c.Workspace))
	if err != nil {
		return nil, err
	}
	mcpNames, mcpOrder, err := names(res.MCPServers(ctx, c.Workspace))
	if err != nil {
		return nil, err
	}
	counts, err := res.SkillCounts(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	skillNames, skillOrder, err := names(res.Skills(ctx, c.Workspace))
	if err != nil {
		return nil, err
	}
	nsOf := map[string]string{}
	for _, id := range agentOrder {
		nsOf[id] = domain.NamespaceAgent
	}
	for _, id := range collectionOrder {
		nsOf[id] = domain.NamespaceSkillCollection
	}
	for _, id := range mcpOrder {
		nsOf[id] = domain.NamespaceMCPServer
	}
	for _, id := range skillOrder {
		if _, ok := nsOf[id]; !ok {
			nsOf[id] = domain.NamespaceSkill
		}
	}
	members, err := s.explorerMemberIDs(ctx, c)
	if err != nil {
		return nil, err
	}
	var objects []string
	for id, ns := range nsOf {
		if namespace == nil || ns == *namespace {
			objects = append(objects, id)
		}
	}
	tuples, err := s.resourceTuples(ctx, objects)
	if err != nil {
		return nil, err
	}
	out := []Relationship{}
	for _, t := range tuples {
		label, ok := domain.GrantLabel(t.Relation)
		if !ok {
			continue
		}
		obj := t.ObjectID()
		ns, ok := nsOf[obj]
		if !ok || (namespace != nil && ns != *namespace) {
			continue
		}
		subject := subjectOf(t)
		var kind, name string
		if id, ok := agentOf(subject); ok {
			kind, name = PrincipalAgent, id
			if n, ok := agentNames[id]; ok {
				name = n
			}
		} else if id, ok := strings.CutPrefix(subject, authz.TypeUser+":"); ok {
			if _, agent := agentNames[id]; !members[id] && !agent {
				continue
			}
			kind, name = PrincipalUser, id
		} else {
			continue
		}
		objectName := obj
		for _, m := range []map[string]string{agentNames, collectionNames, mcpNames, skillNames} {
			if n := m[obj]; n != "" {
				objectName = n
				break
			}
		}
		r := Relationship{Namespace: ns, Object: obj, ObjectName: objectName, Relation: label, Subject: subject, SubjectKind: kind, SubjectName: name, Direct: ns == domain.NamespaceSkill}
		if ns == domain.NamespaceSkillCollection {
			if n, ok := counts[obj]; ok {
				r.Fanout = &n
			}
		}
		out = append(out, r)
	}
	return out, nil
}

// GrantRelationship is create_relationship; audited only when the graph changed.
func (s *Service) GrantRelationship(ctx context.Context, c authn.Caller, w RelationshipWrite) error {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return err
	}
	if err := s.assertObject(ctx, c, w.Namespace, w.Object); err != nil {
		return err
	}
	subject := ""
	if w.SubjectID != nil {
		subject = *w.SubjectID
	}
	if err := s.assertSubject(ctx, c, subject); err != nil {
		return err
	}
	t, err := toGrant(w)
	if err != nil {
		return err
	}
	written, err := authz.WriteIdempotent(ctx, s.d.Graph, t)
	if _, ok := errors.AsType[*authz.OwnershipError](err); ok {
		s.log.ErrorContext(ctx, "Failed to write relation", "tuple", t.String(), "error", err)
		return refusal(503, "Graph authorization write failed")
	}
	if err != nil || !written {
		return err
	}
	return s.auditGrant(ctx, c, "access.grant", w)
}

// RevokeRelationship is delete_relationship; audited only when the graph changed.
func (s *Service) RevokeRelationship(ctx context.Context, c authn.Caller, w RelationshipWrite) error {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return err
	}
	if err := s.assertObject(ctx, c, w.Namespace, w.Object); err != nil {
		return err
	}
	t, err := toGrant(w)
	if err != nil {
		return err
	}
	deleted, err := authz.DeleteIdempotent(ctx, s.d.Graph, t)
	if _, ok := errors.AsType[*authz.OwnershipError](err); ok {
		s.log.ErrorContext(ctx, "Failed to delete relation", "tuple", t.String(), "error", err)
		return refusal(503, "Graph authorization delete failed")
	}
	if err != nil || !deleted {
		return err
	}
	return s.auditGrant(ctx, c, "access.revoke", w)
}

func (s *Service) auditGrant(ctx context.Context, c authn.Caller, action string, w RelationshipWrite) error {
	var subject any
	if w.SubjectID != nil {
		subject = *w.SubjectID
	}
	return s.audit(ctx, c, action, "access_grant", w.Object, map[string]any{"namespace": w.Namespace, "relation": w.Relation, "subject_id": subject})
}

// CheckPermission is check_permission.
func (s *Service) CheckPermission(ctx context.Context, c authn.Caller, namespace, object, relation, subject string) (bool, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return false, err
	}
	if err := s.assertObject(ctx, c, namespace, object); err != nil {
		return false, err
	}
	if err := s.assertSubject(ctx, c, subject); err != nil {
		return false, err
	}
	bit := domain.VerbToBit(relation)
	if !domain.CheckableBit(bit) {
		return false, nil
	}
	ok, err := s.d.Reader.Check(ctx, subject, bit, authz.TypeResource, object)
	if err != nil {
		if !graphError(err) {
			return false, err
		}
		s.log.ErrorContext(ctx, "Graph authorization check failed", "subject", subject, "object", object, "bit", bit, "error", err)
		return false, refusal(503, "Graph authorization check failed")
	}
	return ok, nil
}

// ResolveAccess is resolve_access; kind is one of the four node kinds.
func (s *Service) ResolveAccess(ctx context.Context, c authn.Caller, subject, kind, resourceID string) (Resolution, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return Resolution{}, err
	}
	verb := domain.VerbByKind(kind)
	if err := s.assertObject(ctx, c, domain.NamespaceOfKind(kind), resourceID); err != nil {
		return Resolution{}, err
	}
	if err := s.assertSubject(ctx, c, subject); err != nil {
		return Resolution{}, err
	}
	bit := domain.VerbToBit(verb)
	allowed, err := s.d.Reader.Check(ctx, subject, bit, authz.TypeResource, resourceID)
	if err != nil {
		if !graphError(err) {
			return Resolution{}, err
		}
		s.log.ErrorContext(ctx, "Graph authorization check failed during resolve", "subject", subject, "object", resourceID, "bit", bit, "error", err)
		allowed = false
	}
	agents, err := s.d.Resources.Agents(ctx, c.Workspace, true)
	if err != nil {
		return Resolution{}, err
	}
	id, isAgent := agentOf(subject)
	if !isAgent {
		id = subject
	}
	name := id
	for _, a := range agents {
		if a.ID == id {
			name = a.Name
		}
	}
	hopKind := PrincipalUser
	if isAgent {
		hopKind = PrincipalAgent
	}
	subjectHop := ResolveHop{ID: subject, Name: name, Kind: hopKind, Color: domain.Color(domain.KindAgent, 0)}
	tuples, err := s.resourceTuples(ctx, []string{resourceID})
	if err != nil {
		return Resolution{}, err
	}
	out := Resolution{Allowed: allowed, Verb: verb, Paths: []ResolvePath{}}
	best := 0
	for _, t := range tuples {
		label, ok := domain.GrantLabel(t.Relation)
		if t.ObjectID() != resourceID || !ok || subjectOf(t) == "" || subjectOf(t) != subject {
			continue
		}
		out.Paths = append(out.Paths, ResolvePath{
			Relation: label,
			Hops: []ResolveHop{subjectHop, {
				ID: authz.ObjectRef(authz.TypeResource, resourceID), Name: kind, Kind: kind, Color: domain.Color(domain.KindCollection, 0),
			}},
			Rels: []string{label},
		})
		if rank := domain.GrantRank(t.Relation); rank > best {
			best, out.EffectiveRelation = rank, &label
		}
	}
	return out, nil
}

// SyncMembers is sync_grants: every member row and the owner get their
// Workspace#members tuple; written counts the attempts.
func (s *Service) SyncMembers(ctx context.Context, c authn.Caller) (int, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return 0, err
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return 0, err
	}
	ids, err := s.d.Store.MembershipUserIDs(ctx, q, c.Workspace.ID())
	var w domain.Workspace
	var found bool
	if err == nil {
		w, found, err = s.d.Store.GetWorkspace(ctx, q, c.Workspace.ID())
	}
	release()
	if err != nil {
		return 0, err
	}
	if found && w.OwnerUserID != "" {
		ids = append(ids, w.OwnerUserID)
	}
	slices.Sort(ids)
	ids = slices.Compact(ids)
	written := 0
	for _, id := range ids {
		if _, err := authz.WriteIdempotent(ctx, s.d.Graph, authz.WorkspaceMembership(c.Workspace.ID(), id)); err != nil {
			if own, ok := errors.AsType[*authz.OwnershipError](err); ok {
				return 0, &domain.OwnershipUnavailableError{Err: own}
			}
			return 0, err
		}
		written++
	}
	return written, nil
}
