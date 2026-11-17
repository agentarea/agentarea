//go:build suite

package harness

import (
	"fmt"
	"net/http"
	"regexp"
	"strings"
	"testing"
)

// Workspace is a shared workspace made for one test: Owner created and
// administers it, Member joined it through an invitation, Outsider is in none
// of it and has a workspace of its own (OutsiderPath). Nothing in it is
// shared with another test.
type Workspace struct {
	ID   string
	Slug string

	People *Principals

	Owner     *Client
	Member    *Client
	Outsider  *Client
	Anonymous *Client

	OutsiderID   string
	OutsiderSlug string
}

// NewWorkspace creates the test's workspace and the outsider's.
func NewWorkspace(t testing.TB) *Workspace {
	t.Helper()
	people := People(t)
	w := &Workspace{
		People:    people,
		Owner:     people.Owner.Client(t, "owner"),
		Member:    people.Member.Client(t, "member"),
		Outsider:  people.Outsider.Client(t, "outsider"),
		Anonymous: Anonymous(t),
	}
	name := workspaceName(t)

	var ws struct {
		ID   string `json:"id"`
		Slug string `json:"slug"`
	}
	w.Owner.Post(t, "/v1/workspaces", map[string]any{"name": name}).Expect(http.StatusCreated).Decode(&ws)
	w.ID, w.Slug = ws.ID, ws.Slug

	var invitation struct {
		Token string `json:"token"`
	}
	w.Owner.Post(t, w.Path("/invitations"), map[string]any{"email": people.Member.Email}).
		Expect(http.StatusCreated, http.StatusOK).Decode(&invitation)
	w.Member.Post(t, "/v1/invitations/accept", map[string]any{"token": invitation.Token}).Expect(http.StatusOK)

	var foreign struct {
		ID   string `json:"id"`
		Slug string `json:"slug"`
	}
	w.Outsider.Post(t, "/v1/workspaces", map[string]any{"name": name + " outside"}).
		Expect(http.StatusCreated).Decode(&foreign)
	w.OutsiderID, w.OutsiderSlug = foreign.ID, foreign.Slug
	return w
}

// Path is the workspace-scoped route: Path("/projects/") is
// /v1/workspaces/<slug>/projects/.
func (w *Workspace) Path(route string) string {
	return "/v1/workspaces/" + w.Slug + route
}

// OutsiderPath is the same route in the outsider's own workspace.
func (w *Workspace) OutsiderPath(route string) string {
	return "/v1/workspaces/" + w.OutsiderSlug + route
}

// APIKey creates a workspace API key as the owner and returns a client using it.
func (w *Workspace) APIKey(t testing.TB) *Client {
	t.Helper()
	return w.key(t, "api-key", nil)
}

// AgentKey creates a key bound to one agent of the workspace (the A2A edge
// credential) and returns a client using it.
func (w *Workspace) AgentKey(t testing.TB, agentID string) *Client {
	t.Helper()
	return w.key(t, "agent-key", map[string]any{"agent_id": agentID})
}

func (w *Workspace) key(t testing.TB, name string, extra map[string]any) *Client {
	t.Helper()
	body := map[string]any{"name": "suite " + name}
	for k, v := range extra {
		body[k] = v
	}
	var key struct {
		Token string `json:"token"`
	}
	w.Owner.Post(t, w.Path("/api-keys/"), body).Expect(http.StatusCreated).Decode(&key)
	if !strings.HasPrefix(key.Token, "aat_") {
		t.Fatalf("api key token %q lacks the aat_ prefix", key.Token)
	}
	return Bearer(t, name, key.Token)
}

var unsafeName = regexp.MustCompile(`[^A-Za-z0-9 ]+`)

func workspaceName(t testing.TB) string {
	n := strings.TrimSpace(unsafeName.ReplaceAllString(t.Name(), " "))
	if len(n) > 60 {
		n = n[:60]
	}
	return fmt.Sprintf("suite %s %s", n, randomHex(3))
}
