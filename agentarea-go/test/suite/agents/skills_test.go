//go:build suite

package agents

import (
	"encoding/json"
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func skill(id any, name, slug string, over map[string]any) map[string]any {
	s := map[string]any{
		"id": id, "name": name, "slug": slug, "description": nil, "source_type": "content", "source_url": nil,
		"network_scope": "private", "workspace_id": h.AnyString, "created_at": h.AnyString, "updated_at": h.AnyString,
		"is_catalog": false, "registry_item_id": nil, "update_available": false, "customized": false,
		"registry_name": nil, "registry_scope": nil, "registry_trust": nil, "removed_upstream": false,
	}
	for k, v := range over {
		s[k] = v
	}
	return s
}

func skillCreate(t *testing.T, w *h.Workspace, content string) string {
	t.Helper()
	return w.Owner.Post(t, w.Path("/skills"), map[string]any{"content": content}).Expect(http.StatusOK).Object()["id"].(string)
}

func TestSkillCreateReadUpdateDelete(t *testing.T) {
	w := h.NewWorkspace(t)
	made := w.Owner.Post(t, w.Path("/skills"), map[string]any{"content": "---\nname: PDF tools\ndescription: Reads PDFs\n---\n# PDF\nbody"}).
		Expect(http.StatusOK).Match(skill(h.AnyUUID, "PDF tools", "pdf-tools", map[string]any{"description": "Reads PDFs"})).Object()
	id := made["id"].(string)
	w.Owner.Get(t, w.Path("/skills/"+id)).Expect(http.StatusOK).Match(skill(id, "PDF tools", "pdf-tools", map[string]any{"description": "Reads PDFs"}))
	w.Owner.Get(t, w.Path("/skills/"+id+"/content")).Expect(http.StatusOK).
		Match(map[string]any{"id": id, "name": "PDF tools", "content": "---\nname: PDF tools\ndescription: Reads PDFs\n---\n# PDF\nbody"})
	w.Owner.Get(t, w.Path("/skills/"+id+"/files")).Expect(http.StatusOK).
		Match(map[string]any{"skill_id": id, "files": []any{map[string]any{"path": "SKILL.md", "size": h.AnyNumber, "url": nil}}})
	url := w.Owner.Get(t, w.Path("/skills/"+id+"/files/SKILL.md?redirect=false")).Expect(http.StatusOK).Object()["url"]
	if s, ok := url.(string); !ok || s == "" {
		t.Fatalf("file url %v", url)
	}

	w.Owner.Put(t, w.Path("/skills/"+id), map[string]any{"name": "PDF", "content": "# PDF\nv2"}).Expect(http.StatusOK).
		Match(skill(id, "PDF", "pdf-tools", map[string]any{"description": "Reads PDFs"}))
	versions := w.Owner.Get(t, w.Path("/skills/"+id+"/versions")).Expect(http.StatusOK).Array()
	if len(versions) != 2 || versions[0].(map[string]any)["reason"] != "create" || versions[1].(map[string]any)["current"] != true {
		t.Fatalf("versions %v", versions)
	}
	first := versions[0].(map[string]any)["id"].(string)
	w.Owner.Post(t, w.Path("/skills/"+id+"/versions/"+first+"/rollback"), nil).Expect(http.StatusOK)
	w.Owner.Get(t, w.Path("/skills/"+id+"/content")).Expect(http.StatusOK).Match(map[string]any{"id": id, "name": "PDF",
		"content": "---\nname: PDF tools\ndescription: Reads PDFs\n---\n# PDF\nbody"})

	page := w.Owner.Get(t, w.Path("/skills?include_catalog=false")).Expect(http.StatusOK).Object()
	if page["total"] != json.Number("1") || page["page"] != json.Number("1") || page["has_next"] != false {
		t.Fatalf("list %v", page)
	}
	w.Owner.Put(t, w.Path("/skills/"+id), map[string]any{"name": ""}).Expect(http.StatusUnprocessableEntity)
	w.Outsider.Get(t, w.Path("/skills/"+id)).Expect(http.StatusForbidden, http.StatusNotFound)
	w.Owner.Get(t, w.Path("/skills/not-a-uuid")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Delete(t, w.Path("/skills/"+id)).Expect(http.StatusOK).Match(map[string]any{"status": "deleted", "id": id})
	w.Owner.Get(t, w.Path("/skills/"+id)).Expect(http.StatusNotFound, http.StatusForbidden)
}

func TestSkillCreateValidation(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/skills"), map[string]any{}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/skills"), map[string]any{"content": "x", "github_url": "https://github.com/a/b"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/skills"), map[string]any{"content": "---\na: &x 1\nb: *x\n---\nbody"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/skills"), map[string]any{"github_url": "https://gitlab.com/a/b"}).Expect(http.StatusBadRequest, http.StatusNotImplemented)
}

func TestSkillMembersAndFlatten(t *testing.T) {
	w := h.NewWorkspace(t)
	parent, a, b := skillCreate(t, w, "# Parent"), skillCreate(t, w, "# A"), skillCreate(t, w, "# B")
	w.Owner.Post(t, w.Path("/skills/"+parent+"/members"), map[string]any{"child_skill_id": a, "order": 1, "dependencies": []any{b}}).
		Expect(http.StatusOK).Match(map[string]any{"parent_skill_id": parent, "child_skill_id": a, "order": float64(1), "is_required": true, "dependencies": []any{b}})
	w.Owner.Post(t, w.Path("/skills/"+parent+"/members"), map[string]any{"child_skill_id": b, "order": 2}).Expect(http.StatusOK)
	w.Owner.Post(t, w.Path("/skills/"+parent+"/members"), map[string]any{"child_skill_id": parent}).Expect(http.StatusBadRequest)
	if ms := w.Owner.Get(t, w.Path("/skills/"+parent+"/members")).Expect(http.StatusOK).Array(); len(ms) != 2 {
		t.Fatalf("members %v", ms)
	}
	w.Owner.Get(t, w.Path("/skills/"+parent+"/flatten")).Expect(http.StatusOK).Match([]any{b, a})
	w.Owner.Delete(t, w.Path("/skills/"+parent+"/members/"+a)).Expect(http.StatusOK).
		Match(map[string]any{"status": "removed", "parent_skill_id": parent, "child_skill_id": a})
	w.Owner.Delete(t, w.Path("/skills/"+parent+"/members/"+a)).Expect(http.StatusNotFound)
}
