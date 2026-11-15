// Package authz answers whether a subject may act on an object. Authorization
// is ReBAC over OpenFGA (AGENTAREA_AUTHZ_BACKEND, AGENTAREA_AUTHZ_FGA_*). The
// adapter speaks OpenFGA's HTTP API directly, as Python does
// (rebac/openfga_client.py), so the requests on the wire are the same.
//
// There is one decision point for tool authorization, default-allow,
// evaluated by governance; this package is the graph it consults, not a
// second authority. Reads consult the graph too: list endpoints filter by
// ListObjects (workspace-root reader).
//
// Every operation fails closed: an unreachable graph or an error response is
// an error, never an answer.
package authz

import (
	"context"
	"errors"
	"strconv"
	"strings"
)

// ErrDenied is a refused check (403 permission_denied at the edge, or 404
// where the resource's existence must not leak).
var ErrDenied = errors.New("permission denied")

// ResponseError is an error response from the graph (OpenFGAError).
type ResponseError struct {
	Op     string
	Status int
	Body   string
}

func (e *ResponseError) Error() string {
	return e.Op + " failed (" + strconv.Itoa(e.Status) + "): " + e.Body
}

// UnavailableError is a graph that could not be reached (OpenFGAUnavailableError).
type UnavailableError struct {
	Op  string
	Err error
}

func (e *UnavailableError) Error() string {
	return "OpenFGA " + e.Op + " unreachable: " + e.Err.Error()
}

func (e *UnavailableError) Unwrap() error { return e.Err }

// Tuple is one relationship: User has Relation on Object ("type:id"). User is
// "type:id", "type:*" or a userset "type:id#relation".
type Tuple struct {
	User     string
	Relation string
	Object   string
}

func (t Tuple) String() string { return t.Object + "#" + t.Relation + "@" + t.User }

// ObjectType is the type part of Object.
func (t Tuple) ObjectType() string { typ, _ := SplitObject(t.Object); return typ }

// ObjectID is the id part of Object.
func (t Tuple) ObjectID() string { _, id := SplitObject(t.Object); return id }

// Query selects tuples to read. Type is required, and so is ID or User: the
// graph is never scanned whole (rebac/openfga_client.py _query_key).
type Query struct {
	Type     string
	ID       string
	Relation string
	User     string
}

// ErrUnfilteredRead refuses a Query the server cannot filter.
var ErrUnfilteredRead = errors.New("authz: a read names a type and an object id or a user")

// Validate refuses a query that would read the whole store.
func (q Query) Validate() error {
	if q.Type == "" || (q.ID == "" && q.User == "") || strings.ContainsAny(q.Type, ":#") {
		return ErrUnfilteredRead
	}
	return nil
}

// Matches reports whether t is selected by q (the client-side filter Python
// applies to every page).
func (q Query) Matches(t Tuple) bool {
	typ, id := SplitObject(t.Object)
	return typ == q.Type &&
		(q.ID == "" || id == q.ID) &&
		(q.Relation == "" || t.Relation == q.Relation) &&
		(q.User == "" || t.User == q.User)
}

// CheckItem is one question of a batch.
type CheckItem struct {
	Subject    string
	Relation   string
	ObjectType string
	ObjectID   string
}

// Checker is PermissionService.check: does subject ("User:<id>" or
// "Agent:<id>") have relation on objectType:objectID.
type Checker interface {
	Check(ctx context.Context, subject, relation, objectType, objectID string) (bool, error)
}

// BatchChecker answers several checks in one round trip; answers are in the
// order of items. Any item the graph could not answer fails the whole call.
type BatchChecker interface {
	BatchCheck(ctx context.Context, items []CheckItem) ([]bool, error)
}

// Lister returns the ids of objects of objectType the subject has relation on.
type Lister interface {
	ListObjects(ctx context.Context, subject, relation, objectType string) ([]string, error)
}

// Reader returns every stored tuple q selects, following pagination.
type Reader interface {
	Read(ctx context.Context, q Query) ([]Tuple, error)
}

// Writer writes and deletes tuples in one request, atomically: a tuple that
// already exists (or a delete of one that does not) fails the whole request.
// Ownership is written in the repository that creates the resource, never by
// a separate grant store.
type Writer interface {
	Write(ctx context.Context, writes, deletes []Tuple) error
}

// Graph is the whole port the cluster profile implements over OpenFGA.
type Graph interface {
	Checker
	BatchChecker
	Lister
	Reader
	Writer
}

// Require returns ErrDenied unless the caller's graph subject has relation on
// the object.
func Require(ctx context.Context, ch Checker, caller interface{ GraphSubject() string }, relation, objectType, objectID string) error {
	ok, err := ch.Check(ctx, caller.GraphSubject(), relation, objectType, objectID)
	if err != nil {
		return err
	}
	if !ok {
		return ErrDenied
	}
	return nil
}
