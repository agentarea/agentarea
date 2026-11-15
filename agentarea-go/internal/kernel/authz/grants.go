package authz

import (
	"context"
	"errors"
	"net/http"
	"slices"
	"strings"

	"golang.org/x/sync/errgroup"
)

// OwnershipError is a grant the graph could not record (ResourceOwnershipError):
// the caller must not proceed, and the edge answers 503
// resource_ownership_unavailable with Error() as the detail. A resource whose
// ownership was not recorded is unreachable to everyone, its creator included.
type OwnershipError struct {
	Msg string
	Err error
}

func (e *OwnershipError) Error() string { return e.Msg }

func (e *OwnershipError) Unwrap() error { return e.Err }

// The graph answers a write of an existing tuple, and a delete of a missing
// one, with 400 and a message naming both cases; each request here carries
// one tuple, so the operation says which it was (rebac/ownership.py).
func isExistingTupleError(err error) bool {
	body, ok := badRequestBody(err)
	return ok && (strings.Contains(body, "already exists") || strings.Contains(body, "tuple to be written already existed"))
}

func isMissingTupleError(err error) bool {
	body, ok := badRequestBody(err)
	return ok && (strings.Contains(body, "does not exist") || strings.Contains(body, "did not exist"))
}

func badRequestBody(err error) (string, bool) {
	var re *ResponseError
	if !errors.As(err, &re) || re.Status != http.StatusBadRequest {
		return "", false
	}
	return strings.ToLower(re.Body), true
}

// WriteIdempotent writes t; one already there is not an error. It reports
// whether the graph changed.
func WriteIdempotent(ctx context.Context, w Writer, t Tuple) (bool, error) {
	if err := w.Write(ctx, []Tuple{t}, nil); err != nil {
		if isExistingTupleError(err) {
			return false, nil
		}
		return false, &OwnershipError{Msg: "OpenFGA grant write failed", Err: err}
	}
	return true, nil
}

// DeleteIdempotent deletes t; one already gone is not an error. It reports
// whether the graph changed.
func DeleteIdempotent(ctx context.Context, w Writer, t Tuple) (bool, error) {
	if err := w.Write(ctx, nil, []Tuple{t}); err != nil {
		if isMissingTupleError(err) {
			return false, nil
		}
		return false, &OwnershipError{Msg: "OpenFGA grant delete failed", Err: err}
	}
	return true, nil
}

// GrantResourceOwner attaches a new resource to its workspace's root project
// and grants owner each of relations on it, one idempotent write per tuple
// (rebac/ownership.py grant_resource_owner). It runs before the row's commit:
// a failed grant rolls the insert back.
func GrantResourceOwner(ctx context.Context, w Writer, resourceID, workspaceID, owner string, relations []string) error {
	object := ObjectRef(TypeResource, resourceID)
	if _, err := WriteIdempotent(ctx, w, Tuple{User: RootProject(workspaceID), Relation: RelProject, Object: object}); err != nil {
		return err
	}
	for _, rel := range relations {
		if _, err := WriteIdempotent(ctx, w, Tuple{User: owner, Relation: rel, Object: object}); err != nil {
			return err
		}
	}
	return nil
}

// AgentEnrollment is what a new agent's runs act with: membership, reading
// its workspace as a plain member does, and invoking itself.
func AgentEnrollment(agentID, workspaceID string) []Tuple {
	subject := AgentSubject(agentID)
	return []Tuple{
		{User: subject, Relation: RelMembers, Object: ObjectRef(TypeWorkspace, workspaceID)},
		{User: subject, Relation: RelReader, Object: RootProject(workspaceID)},
		{User: subject, Relation: RelInvoker, Object: ObjectRef(TypeResource, agentID)},
	}
}

// EnrollAgent writes AgentEnrollment.
func EnrollAgent(ctx context.Context, w Writer, agentID, workspaceID string) error {
	for _, t := range AgentEnrollment(agentID, workspaceID) {
		if _, err := WriteIdempotent(ctx, w, t); err != nil {
			return err
		}
	}
	return nil
}

// WithdrawAgent deletes AgentEnrollment once the agent is gone.
func WithdrawAgent(ctx context.Context, w Writer, agentID, workspaceID string) error {
	for _, t := range AgentEnrollment(agentID, workspaceID) {
		if _, err := DeleteIdempotent(ctx, w, t); err != nil {
			return err
		}
	}
	return nil
}

// ReadWriter reads and writes tuples.
type ReadWriter interface {
	Reader
	Writer
}

// RevokeResource deletes every tuple on resource:<id> after its row's delete
// commits; the caller logs a failure, the row is already gone.
func RevokeResource(ctx context.Context, rw ReadWriter, resourceID string) error {
	tuples, err := rw.Read(ctx, Query{Type: TypeResource, ID: resourceID})
	if err != nil {
		return err
	}
	for _, t := range tuples {
		if err := rw.Write(ctx, nil, []Tuple{t}); err != nil {
			return err
		}
	}
	return nil
}

// WorkspaceSeed is what a new workspace needs before its row is inserted:
// the creator is a member and admin, and the root project belongs to it.
func WorkspaceSeed(workspaceID, creatorUserID string) []Tuple {
	ws := ObjectRef(TypeWorkspace, workspaceID)
	creator := ObjectRef(TypeUser, creatorUserID)
	return []Tuple{
		{User: creator, Relation: RelMembers, Object: ws},
		{User: creator, Relation: RelAdmin, Object: ws},
		{User: ws, Relation: RelWorkspace, Object: RootProject(workspaceID)},
	}
}

// SeedWorkspace writes WorkspaceSeed, idempotently
// (api/v1/_access_control_grants.py seed_workspace).
func SeedWorkspace(ctx context.Context, w Writer, workspaceID, creatorUserID string) error {
	for _, t := range WorkspaceSeed(workspaceID, creatorUserID) {
		if _, err := WriteIdempotent(ctx, w, t); err != nil {
			return err
		}
	}
	return nil
}

// WorkspaceMembership is Workspace:<ws>#members@User:<user>.
func WorkspaceMembership(workspaceID, userID string) Tuple {
	return Tuple{User: UserSubject(userID), Relation: RelMembers, Object: ObjectRef(TypeWorkspace, workspaceID)}
}

// WorkspaceBaselineRole is what membership grants: read over the root
// project, which cascades to every resource under it. Membership alone
// confers nothing in the model.
func WorkspaceBaselineRole(workspaceID, userID string) Tuple {
	return Tuple{User: UserSubject(userID), Relation: RelReader, Object: RootProject(workspaceID)}
}

// GrantWorkspaceMembership writes membership and the baseline role. Errors
// other than "already there" are returned as the graph gave them; the edge
// answers 503 "Workspace membership graph unavailable".
func GrantWorkspaceMembership(ctx context.Context, w Writer, workspaceID, userID string) error {
	for _, t := range []Tuple{WorkspaceMembership(workspaceID, userID), WorkspaceBaselineRole(workspaceID, userID)} {
		if err := w.Write(ctx, []Tuple{t}, nil); err != nil && !isExistingTupleError(err) {
			return err
		}
	}
	return nil
}

// RevokeWorkspaceMembership deletes what GrantWorkspaceMembership wrote.
func RevokeWorkspaceMembership(ctx context.Context, w Writer, workspaceID, userID string) error {
	for _, t := range []Tuple{WorkspaceMembership(workspaceID, userID), WorkspaceBaselineRole(workspaceID, userID)} {
		if err := w.Write(ctx, nil, []Tuple{t}); err != nil && !isMissingTupleError(err) {
			return err
		}
	}
	return nil
}

// IsWorkspaceMember checks Workspace:<ws>#members for the user.
func IsWorkspaceMember(ctx context.Context, ch Checker, workspaceID, userID string) (bool, error) {
	return ch.Check(ctx, UserSubject(userID), RelMembers, TypeWorkspace, workspaceID)
}

// WorkspaceMemberIDs are the users (not agents) with a members tuple on the
// workspace, sorted.
func WorkspaceMemberIDs(ctx context.Context, r Reader, workspaceID string) ([]string, error) {
	tuples, err := r.Read(ctx, Query{Type: TypeWorkspace, ID: workspaceID, Relation: RelMembers})
	if err != nil {
		return nil, err
	}
	var ids []string
	for _, t := range tuples {
		if id, ok := strings.CutPrefix(t.User, TypeUser+":"); ok {
			ids = append(ids, id)
		}
	}
	slices.Sort(ids)
	return slices.Compact(ids), nil
}

// MemberWorkspaceIDs are the workspaces the user has a members tuple on, sorted.
func MemberWorkspaceIDs(ctx context.Context, r Reader, userID string) ([]string, error) {
	tuples, err := r.Read(ctx, Query{Type: TypeWorkspace, Relation: RelMembers, User: UserSubject(userID)})
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(tuples))
	for _, t := range tuples {
		ids = append(ids, t.ObjectID())
	}
	slices.Sort(ids)
	return slices.Compact(ids), nil
}

// ReadableResourceIDs are the resource ids subject may read: everything under
// the workspace root project for a member, plus direct grants. No fallback:
// an unreachable graph is an error, never "everything" or "nothing".
func ReadableResourceIDs(ctx context.Context, l Lister, subject string) (map[string]struct{}, error) {
	ids, err := l.ListObjects(ctx, subject, CanRead, TypeResource)
	if err != nil {
		return nil, err
	}
	out := make(map[string]struct{}, len(ids))
	for _, id := range ids {
		out[id] = struct{}{}
	}
	return out, nil
}

// PersonalTuples mark a connection personal: only its creator and the agents
// it was lent to may call through it.
func PersonalTuples(connectionID string) []Tuple {
	object := ObjectRef(TypeResource, connectionID)
	return []Tuple{
		{User: EveryUser, Relation: RelPersonal, Object: object},
		{User: EveryAgent, Relation: RelPersonal, Object: object},
	}
}

// MakePersonal writes PersonalTuples.
func MakePersonal(ctx context.Context, w Writer, connectionID string) error {
	for _, t := range PersonalTuples(connectionID) {
		if _, err := WriteIdempotent(ctx, w, t); err != nil {
			return err
		}
	}
	return nil
}

// ShareWithWorkspace deletes PersonalTuples: whoever reads it may use it.
func ShareWithWorkspace(ctx context.Context, w Writer, connectionID string) error {
	for _, t := range PersonalTuples(connectionID) {
		if _, err := DeleteIdempotent(ctx, w, t); err != nil {
			return err
		}
	}
	return nil
}

const personalReadConcurrency = 16

// PersonalConnectionIDs is which of ids are personal: one read per id.
func PersonalConnectionIDs(ctx context.Context, r Reader, ids []string) (map[string]struct{}, error) {
	personal := make([]bool, len(ids))
	g, gctx := errgroup.WithContext(ctx)
	g.SetLimit(personalReadConcurrency)
	for i, id := range ids {
		g.Go(func() error {
			tuples, err := r.Read(gctx, Query{Type: TypeResource, ID: id})
			if err != nil {
				return err
			}
			personal[i] = slices.ContainsFunc(tuples, func(t Tuple) bool {
				return t.Relation == RelPersonal && t.User == EveryUser
			})
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		return nil, err
	}
	out := make(map[string]struct{})
	for i, id := range ids {
		if personal[i] {
			out[id] = struct{}{}
		}
	}
	return out, nil
}

// IsConnectionOwner is whether subject created the connection: the direct
// manager, not can_manage (a workspace admin manages every connection, but
// sharing someone's personal account is its owner's call alone).
func IsConnectionOwner(ctx context.Context, ch Checker, subject, connectionID string) (bool, error) {
	return ch.Check(ctx, subject, RelManager, TypeResource, connectionID)
}

// ConnectionLoan lets an agent call through a connection, whoever runs it.
func ConnectionLoan(connectionID, agentID string) Tuple {
	return Tuple{User: AgentSubject(agentID), Relation: RelConnectionUser, Object: ObjectRef(TypeResource, connectionID)}
}

// LendConnection writes ConnectionLoan.
func LendConnection(ctx context.Context, w Writer, connectionID, agentID string) error {
	_, err := WriteIdempotent(ctx, w, ConnectionLoan(connectionID, agentID))
	return err
}

// WithdrawConnection deletes ConnectionLoan.
func WithdrawConnection(ctx context.Context, w Writer, connectionID, agentID string) error {
	_, err := DeleteIdempotent(ctx, w, ConnectionLoan(connectionID, agentID))
	return err
}
