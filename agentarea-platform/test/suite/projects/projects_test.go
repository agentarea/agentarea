//go:build suite

// Package projects pins /v1/workspaces/{workspace}/projects
// (.omc/research/go-migration/dossiers/projects.md, section 2).
package projects

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

func project(w *h.Workspace, id any, createdBy, name string, description, instructions, parent any) map[string]any {
	return map[string]any{
		"id":                id,
		"workspace_id":      w.ID,
		"created_by":        createdBy,
		"name":              name,
		"description":       description,
		"instructions":      instructions,
		"parent_project_id": parent,
		"skills":            []any{},
		"mcp_instances":     []any{},
		"agents":            []any{},
	}
}

func create(t *testing.T, c *h.Client, collection string, body map[string]any) map[string]any {
	t.Helper()
	return c.Post(t, collection, body).Expect(http.StatusCreated).Object()
}

func TestCreateStripsNameAndReadsBack(t *testing.T) {
	w := h.NewWorkspace(t)

	resp := w.Owner.Post(t, w.Path("/projects/"), map[string]any{
		"name": "  Roadmap  ", "description": "Q3 plan", "instructions": "Answer in English.",
	}).Expect(http.StatusCreated)
	if ct := resp.ContentType(); ct != "application/json" {
		t.Fatalf("content-type %q", ct)
	}
	want := project(w, h.AnyUUID, w.People.Owner.ID, "Roadmap", "Q3 plan", "Answer in English.", nil)
	created := resp.Match(want).Object()

	want["id"] = created["id"]
	w.Owner.Get(t, w.Path("/projects/"+created["id"].(string))).Expect(http.StatusOK).Match(want)
}

func TestListIsTheWorkspacesProjects(t *testing.T) {
	w := h.NewWorkspace(t)
	a := create(t, w.Owner, w.Path("/projects/"), map[string]any{"name": "Alpha"})
	b := create(t, w.Owner, w.Path("/projects/"), map[string]any{"name": "Beta", "description": "second"})

	// No ORDER BY in Python (dossier section 10, item 13): membership, not order.
	w.Owner.Get(t, w.Path("/projects/")).Expect(http.StatusOK).Match(h.Unordered(
		project(w, a["id"], w.People.Owner.ID, "Alpha", nil, nil, nil),
		project(w, b["id"], w.People.Owner.ID, "Beta", "second", nil, nil),
	))

	w.Outsider.Get(t, w.OutsiderPath("/projects/")).Expect(http.StatusOK).Match([]any{})

	// FastAPI redirects the slashless collection path to the slashed one.
	resp := w.Owner.Get(t, w.Path("/projects")).Expect(http.StatusTemporaryRedirect)
	if loc := resp.Header.Get("Location"); loc != h.Current(t).BaseURL+w.Path("/projects/") {
		t.Fatalf("Location %q", loc)
	}
}

func TestNestingRefusesCyclesAndDeleteOrphansChildren(t *testing.T) {
	w := h.NewWorkspace(t)
	root := create(t, w.Owner, w.Path("/projects/"), map[string]any{"name": "Root"})
	rootID := root["id"].(string)
	child := create(t, w.Owner, w.Path("/projects/"), map[string]any{"name": "Child", "parent_project_id": rootID})
	childID := child["id"].(string)
	if child["parent_project_id"] != rootID {
		t.Fatalf("child parent_project_id = %v, want %s", child["parent_project_id"], rootID)
	}

	cycle := h.Problem(http.StatusBadRequest, "bad_request", "A project cannot be nested under itself or its own subproject")
	w.Owner.Patch(t, w.Path("/projects/"+rootID), map[string]any{"parent_project_id": childID}).
		Expect(http.StatusBadRequest).Match(cycle)
	w.Owner.Patch(t, w.Path("/projects/"+rootID), map[string]any{"parent_project_id": rootID}).
		Expect(http.StatusBadRequest).Match(cycle)

	foreign := create(t, w.Outsider, w.OutsiderPath("/projects/"), map[string]any{"name": "Elsewhere"})
	w.Owner.Post(t, w.Path("/projects/"), map[string]any{"name": "Stray", "parent_project_id": foreign["id"]}).
		Expect(http.StatusNotFound).Match(h.Problem(http.StatusNotFound, "not_found", "Parent project not found"))

	w.Owner.Delete(t, w.Path("/projects/"+rootID)).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/projects/"+childID)).Expect(http.StatusOK).
		Match(project(w, childID, w.People.Owner.ID, "Child", nil, nil, nil))
}

func TestOutsiderGetsNotFound(t *testing.T) {
	w := h.NewWorkspace(t)
	p := create(t, w.Owner, w.Path("/projects/"), map[string]any{"name": "Private"})
	id := p["id"].(string)

	notFound := h.Problem(http.StatusNotFound, "http_error", "Project not found")
	w.Outsider.Get(t, w.OutsiderPath("/projects/"+id)).Expect(http.StatusNotFound).Match(notFound)
	w.Outsider.Patch(t, w.OutsiderPath("/projects/"+id), map[string]any{"name": "Taken"}).
		Expect(http.StatusNotFound).Match(notFound)
	w.Outsider.Delete(t, w.OutsiderPath("/projects/"+id)).Expect(http.StatusNotFound).Match(notFound)

	// Naming the owner's workspace in the path is refused before any lookup.
	w.Outsider.Get(t, w.Path("/projects/"+id)).Expect(http.StatusForbidden).
		Match(h.Problem(http.StatusForbidden, "http_error", "User is not a member of the requested workspace"))
	w.Anonymous.Get(t, w.Path("/projects/"+id)).Expect(http.StatusUnauthorized).
		Match(h.Problem(http.StatusUnauthorized, "http_error", "Missing authentication credentials"))

	w.Owner.Get(t, w.Path("/projects/"+id)).Expect(http.StatusOK).
		Match(project(w, id, w.People.Owner.ID, "Private", nil, nil, nil))
}

func TestMemberHasFullAccess(t *testing.T) {
	w := h.NewWorkspace(t)
	owners := create(t, w.Owner, w.Path("/projects/"), map[string]any{"name": "Owner's"})
	ownersID := owners["id"].(string)

	// No FGA check on projects: any member reads, edits and deletes any project.
	w.Member.Get(t, w.Path("/projects/"+ownersID)).Expect(http.StatusOK).
		Match(project(w, ownersID, w.People.Owner.ID, "Owner's", nil, nil, nil))
	w.Member.Patch(t, w.Path("/projects/"+ownersID), map[string]any{"name": "Renamed", "description": "by member"}).
		Expect(http.StatusOK).
		Match(project(w, ownersID, w.People.Owner.ID, "Renamed", "by member", nil, nil))

	members := create(t, w.Member, w.Path("/projects/"), map[string]any{"name": "Member's"})
	w.Owner.Get(t, w.Path("/projects/")).Expect(http.StatusOK).Match(h.Unordered(
		project(w, ownersID, w.People.Owner.ID, "Renamed", "by member", nil, nil),
		project(w, members["id"], w.People.Member.ID, "Member's", nil, nil, nil),
	))

	w.Member.Delete(t, w.Path("/projects/"+ownersID)).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/projects/"+ownersID)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Project not found"))

	// A workspace API key acts as its creator, a member like any other.
	w.APIKey(t).Get(t, w.Path("/projects/")).Expect(http.StatusOK).Match([]any{
		project(w, members["id"], w.People.Member.ID, "Member's", nil, nil, nil),
	})
}
