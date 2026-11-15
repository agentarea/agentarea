//go:build suite

// Package identity pins the identity routes
// (.omc/research/go-migration/dossiers/identity.md): workspaces, members,
// invitations, API keys, principals, external identities, the access
// explorer and the logo.
package identity

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/url"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

const notAdmin = "Only a workspace admin may perform this action"

func httpError(status int, detail string) map[string]any {
	return h.Problem(status, "http_error", detail)
}

func scopeRefused(action string) map[string]any {
	return h.Problem(http.StatusForbidden, "permission_denied", "This credential cannot "+action+"; sign in as a user to do it")
}

func find(t *testing.T, list []any, key, value string) map[string]any {
	t.Helper()
	for _, item := range list {
		if o, ok := item.(map[string]any); ok && o[key] == value {
			return o
		}
	}
	return nil
}

func TestWorkspacesListedWithAuthority(t *testing.T) {
	w := h.NewWorkspace(t)
	shared := map[string]any{"id": w.ID, "slug": w.Slug, "name": h.AnyString, "owner_user_id": w.People.Owner.ID, "logo_url": nil}

	owned := w.Owner.Get(t, "/v1/workspaces").Expect(http.StatusOK).Array()
	got := find(t, owned, "id", w.ID)
	shared["can_administer"] = true
	if err := h.Compare(got, shared); err != nil {
		t.Fatalf("owner: %v", err)
	}
	personal := find(t, owned, "id", w.People.Owner.ID)
	if personal == nil || personal["name"] != "Personal" || personal["can_administer"] != true || personal["owner_user_id"] != w.People.Owner.ID {
		t.Fatalf("owner's personal workspace %v", personal)
	}

	joined := w.Member.Get(t, "/v1/workspaces").Expect(http.StatusOK).Array()
	shared["can_administer"] = false
	if err := h.Compare(find(t, joined, "id", w.ID), shared); err != nil {
		t.Fatalf("member: %v", err)
	}
	if find(t, w.Outsider.Get(t, "/v1/workspaces").Expect(http.StatusOK).Array(), "id", w.ID) != nil {
		t.Fatal("the outsider lists the workspace")
	}

	// An API key provisions nothing and lists only its own workspace.
	shared["can_administer"] = true
	w.APIKey(t).Get(t, "/v1/workspaces").Expect(http.StatusOK).Match([]any{shared})
	w.Anonymous.Get(t, "/v1/workspaces").Expect(http.StatusUnauthorized)
}

func TestMembersListedWithIdentities(t *testing.T) {
	w := h.NewWorkspace(t)
	want := h.Unordered(
		map[string]any{
			"id": w.People.Owner.ID, "workspace_id": w.ID, "user_id": w.People.Owner.ID,
			"email": w.People.Owner.Email, "display_name": w.People.Owner.Email,
			"joined_at": nil, "invitation_id": nil, "is_owner": true,
		},
		map[string]any{
			"id": w.People.Member.ID, "workspace_id": w.ID, "user_id": w.People.Member.ID,
			"email": w.People.Member.Email, "display_name": w.People.Member.Email,
			"joined_at": h.AnyTimestamp, "invitation_id": h.AnyUUID, "is_owner": false,
		},
	)
	w.Owner.Get(t, w.Path("/members")).Expect(http.StatusOK).Match(want)
	w.Member.Get(t, w.Path("/members")).Expect(http.StatusOK).Match(want)
	w.Outsider.Get(t, w.Path("/members")).Expect(http.StatusForbidden).
		Match(httpError(http.StatusForbidden, "User is not a member of the requested workspace"))
}

func TestInvitationsAreAdminOnly(t *testing.T) {
	w := h.NewWorkspace(t)
	inv := w.Owner.Post(t, w.Path("/invitations"), map[string]any{}).Expect(http.StatusCreated).Object()
	id := inv["id"].(string)

	listed := w.Owner.Get(t, w.Path("/invitations")).Expect(http.StatusOK).Array()
	if err := h.Compare(find(t, listed, "id", id), map[string]any{
		"id": id, "workspace_id": w.ID, "email": nil, "invited_by": w.People.Owner.ID,
		"invited_by_display_name": w.People.Owner.Email, "status": "pending",
		"expires_at": h.AnyTimestamp, "accepted_at": nil, "accepted_by_user_id": nil, "created_at": h.AnyTimestamp,
	}); err != nil {
		t.Fatal(err)
	}

	w.Member.Get(t, w.Path("/invitations")).Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, notAdmin))
	w.Member.Delete(t, w.Path("/invitations/"+id)).Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, notAdmin))
	w.Outsider.Delete(t, w.OutsiderPath("/invitations/"+id)).Expect(http.StatusNotFound).
		Match(httpError(http.StatusNotFound, "Invitation not found"))

	w.Owner.Delete(t, w.Path("/invitations/"+id)).Expect(http.StatusNoContent)
	w.Owner.Delete(t, w.Path("/invitations/"+id)).Expect(http.StatusNoContent)
	if find(t, w.Owner.Get(t, w.Path("/invitations")).Expect(http.StatusOK).Array(), "id", id) != nil {
		t.Fatal("a revoked invitation is still listed")
	}
	w.Outsider.Post(t, "/v1/invitations/accept", map[string]any{"token": inv["token"]}).Expect(http.StatusGone).
		Match(httpError(http.StatusGone, "invitation revoked"))
}

func TestInvitationPreview(t *testing.T) {
	w := h.NewWorkspace(t)
	inv := w.Owner.Post(t, w.Path("/invitations"), map[string]any{"email": strings.ToUpper(w.People.Outsider.Email)}).
		Expect(http.StatusCreated).Object()

	w.Outsider.Post(t, "/v1/invitations/preview", map[string]any{"token": inv["token"]}).Expect(http.StatusOK).
		Match(map[string]any{
			"workspace_name": h.AnyString, "inviter_display_name": w.People.Owner.Email,
			"inviter_email": w.People.Owner.Email, "expires_at": inv["expires_at"],
		})
	w.Member.Post(t, "/v1/invitations/preview", map[string]any{"token": inv["token"]}).Expect(http.StatusForbidden).
		Match(httpError(http.StatusForbidden, "invitation addressed to another account"))
	w.Outsider.Post(t, "/v1/invitations/preview", map[string]any{"token": "nope"}).Expect(http.StatusNotFound).
		Match(httpError(http.StatusNotFound, "invalid token"))
	w.Anonymous.Post(t, "/v1/invitations/preview", map[string]any{"token": inv["token"]}).Expect(http.StatusUnauthorized)
}

func TestMemberRemoval(t *testing.T) {
	w := h.NewWorkspace(t)
	leaver := h.NewUser(t, "leaver")
	lc := leaver.Client(t, "leaver")
	inv := w.Owner.Post(t, w.Path("/invitations"), map[string]any{}).Expect(http.StatusCreated).Object()
	lc.Post(t, "/v1/invitations/accept", map[string]any{"token": inv["token"]}).Expect(http.StatusOK)
	var key struct {
		Token string `json:"token"`
	}
	lc.Post(t, w.Path("/api-keys/"), map[string]any{"name": "leaver"}).Expect(http.StatusCreated).Decode(&key)
	leaverKey := h.Bearer(t, "leaver-key", key.Token)
	leaverKey.Get(t, w.Path("/members")).Expect(http.StatusOK)

	w.Member.Delete(t, w.Path("/members/"+leaver.ID)).Expect(http.StatusForbidden).
		Match(httpError(http.StatusForbidden, "Only the workspace owner can remove other members."))
	w.Member.Delete(t, w.Path("/members/"+w.People.Owner.ID)).Expect(http.StatusConflict).
		Match(httpError(http.StatusConflict, "The workspace owner cannot be removed; transfer ownership first."))
	w.Owner.Delete(t, w.Path("/members/nobody")).Expect(http.StatusNotFound).
		Match(httpError(http.StatusNotFound, "Member not found"))

	lc.Delete(t, w.Path("/members/"+leaver.ID)).Expect(http.StatusNoContent)
	lc.Get(t, w.Path("/members")).Expect(http.StatusForbidden)
	leaverKey.Get(t, w.Path("/members")).Expect(http.StatusUnauthorized)
	lc.Post(t, "/v1/invitations/accept", map[string]any{"token": inv["token"]}).Expect(http.StatusGone)

	w.Owner.Delete(t, w.Path("/members/"+w.People.Member.ID)).Expect(http.StatusNoContent)
	w.Member.Get(t, w.Path("/members")).Expect(http.StatusForbidden)
}

func TestAPIKeysCreatorOrAdmin(t *testing.T) {
	w := h.NewWorkspace(t)
	owners := w.Owner.Post(t, w.Path("/api-keys/"), map[string]any{"name": "owner's"}).Expect(http.StatusCreated).Object()
	members := w.Member.Post(t, w.Path("/api-keys/"), map[string]any{"name": "member's"}).Expect(http.StatusCreated).Object()
	ownerKey, memberKey := owners["id"].(string), members["id"].(string)

	shown := map[string]any{
		"id": memberKey, "name": "member's", "token_prefix": members["token_prefix"], "is_active": true,
		"expires_at": nil, "access_count": h.AnyNumber, "last_accessed_at": h.Any, "created_at": h.AnyTimestamp, "agent_id": nil,
	}
	w.Member.Get(t, w.Path("/api-keys/")).Expect(http.StatusOK).Match([]any{shown})
	if find(t, w.Owner.Get(t, w.Path("/api-keys/")).Expect(http.StatusOK).Array(), "id", memberKey) == nil {
		t.Fatal("the admin does not see the member's key")
	}
	w.Member.Get(t, w.Path("/api-keys/"+memberKey)).Expect(http.StatusOK).Match(shown)
	w.Member.Get(t, w.Path("/api-keys/"+ownerKey)).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "API key not found"))
	w.Member.Delete(t, w.Path("/api-keys/"+ownerKey)).Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, notAdmin))
	w.Outsider.Get(t, w.OutsiderPath("/api-keys/"+memberKey)).Expect(http.StatusNotFound)

	w.APIKey(t).Delete(t, w.Path("/api-keys/"+memberKey)).Expect(http.StatusForbidden).Match(scopeRefused("revoke API keys"))
	w.Owner.Delete(t, w.Path("/api-keys/"+memberKey)).Expect(http.StatusNoContent)
	shown["is_active"] = false
	w.Member.Get(t, w.Path("/api-keys/"+memberKey)).Expect(http.StatusOK).Match(shown)
	w.Owner.Get(t, w.Path("/api-keys/?agent_id=nope")).Expect(http.StatusUnprocessableEntity)
}

func TestPrincipalsResolveKnownIDsOnly(t *testing.T) {
	w := h.NewWorkspace(t)
	q := url.Values{"ids": {w.People.Member.ID, "system", "unknown-id", w.People.Member.ID}}
	w.Owner.Get(t, w.Path("/principals?"+q.Encode())).Expect(http.StatusOK).Match([]any{
		map[string]any{"id": w.People.Member.ID, "type": "user", "display_name": w.People.Member.Email, "email": w.People.Member.Email},
		map[string]any{"id": "system", "type": "platform", "display_name": nil, "email": nil},
	})
	w.Owner.Get(t, w.Path("/principals")).Expect(http.StatusOK).Match([]any{})
}

func TestExternalIdentities(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Get(t, "/v1/me/external-identities").Expect(http.StatusOK).Match([]any{})
	w.Owner.Delete(t, "/v1/me/external-identities/00000000-0000-4000-8000-000000000000").Expect(http.StatusNotFound).
		Match(httpError(http.StatusNotFound, "No such linked account"))
	key := w.APIKey(t)
	key.Post(t, "/v1/me/external-identities/telegram/link", map[string]any{"bot": "agentarea_bot"}).
		Expect(http.StatusForbidden).Match(scopeRefused("link a messenger account"))
	w.Owner.Post(t, "/v1/me/external-identities/telegram/link", map[string]any{"bot": "no"}).Expect(http.StatusUnprocessableEntity)
	link := w.Owner.Post(t, "/v1/me/external-identities/telegram/link", map[string]any{"bot": "agentarea_bot"}).
		Expect(http.StatusOK).Object()
	if u, _ := link["url"].(string); !strings.HasPrefix(u, "https://t.me/agentarea_bot?start=link_") || link["expires_in"] != json.Number("600") {
		t.Fatalf("link %v", link)
	}
}

func TestAccessExplorerIsAdminOnly(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Member.Get(t, w.Path("/access-control/graph")).Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, notAdmin))
	w.Member.Post(t, w.Path("/access-control/sync"), nil).Expect(http.StatusForbidden)
	w.Owner.Get(t, w.Path("/access-control/graph")).Expect(http.StatusOK).Match(map[string]any{
		"enabled": true, "nodes": []any{}, "edges": []any{},
		"stats": map[string]any{"governed_skill_count": h.AnyNumber, "rule_count": h.AnyNumber, "direct_exception_count": h.AnyNumber},
	})
	w.Owner.Post(t, w.Path("/access-control/sync"), nil).Expect(http.StatusOK).Match(map[string]any{"written": h.AnyNumber, "collections": h.AnyNumber})
	w.Owner.Get(t, w.Path("/access-control/relationships?namespace=Workspace")).Expect(http.StatusUnprocessableEntity).
		Match(httpError(http.StatusUnprocessableEntity, "Unsupported namespace: 'Workspace'"))
	w.Owner.Post(t, w.Path("/access-control/check"), map[string]any{
		"namespace": "Agent", "object": "not-a-uuid", "relation": "use", "subject_id": "User:" + w.People.Member.ID,
	}).Expect(http.StatusUnprocessableEntity).Match(httpError(http.StatusUnprocessableEntity, "Invalid object id: 'not-a-uuid'"))
}

func png() []byte { return []byte("\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") }

func logoBody(t *testing.T, data []byte) (http.Header, []byte) {
	t.Helper()
	var b bytes.Buffer
	mw := multipart.NewWriter(&b)
	fw, err := mw.CreateFormFile("file", "logo.png")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = fw.Write(data)
	if err := mw.Close(); err != nil {
		t.Fatal(err)
	}
	return http.Header{"Content-Type": {mw.FormDataContentType()}}, b.Bytes()
}

func TestLogo(t *testing.T) {
	w := h.NewWorkspace(t)
	header, body := logoBody(t, png())
	w.Member.Do(t, h.Request{Method: http.MethodPut, Path: w.Path("/logo"), Header: header, Body: body}).
		Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, notAdmin))
	set := w.Owner.Do(t, h.Request{Method: http.MethodPut, Path: w.Path("/logo"), Header: header, Body: body}).
		Expect(http.StatusOK).Object()
	if u, _ := set["logo_url"].(string); u == "" || set["can_administer"] != true {
		t.Fatalf("set %v", set)
	}
	header, body = logoBody(t, []byte("GIF89a"))
	w.Owner.Do(t, h.Request{Method: http.MethodPut, Path: w.Path("/logo"), Header: header, Body: body}).
		Expect(http.StatusUnprocessableEntity).Match(httpError(http.StatusUnprocessableEntity, "Logo must be a PNG, JPEG or WebP image"))
	w.Owner.Delete(t, w.Path("/logo")).Expect(http.StatusOK).Match(map[string]any{
		"id": w.ID, "slug": w.Slug, "name": h.AnyString, "owner_user_id": w.People.Owner.ID, "can_administer": true, "logo_url": nil,
	})
}
