//go:build suite

package agents

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

func taskDef(id any, name, agentID string, params map[string]any) map[string]any {
	return map[string]any{
		"id": id, "name": name, "description": "d", "agent_id": agentID, "parameters": params,
		"created_by": h.AnyString, "created_at": h.AnyString, "updated_at": h.AnyString,
	}
}

func TestTaskDefinitionLifecycle(t *testing.T) {
	w := h.NewWorkspace(t)
	agentID := create(t, w.Owner, w, map[string]any{"name": "Runner", "tools": []any{}})["id"].(string)
	made := w.Owner.Post(t, w.Path("/task-definitions/"), map[string]any{"name": " Nightly ", "description": "d", "agent_id": agentID, "parameters": map[string]any{"a": 1}}).
		Expect(http.StatusCreated).Match(taskDef(h.AnyUUID, "Nightly", agentID, map[string]any{"a": 1})).Object()
	id := made["id"].(string)
	w.Owner.Get(t, w.Path("/task-definitions/?agent_id="+agentID)).Expect(http.StatusOK).Match([]any{taskDef(id, "Nightly", agentID, map[string]any{"a": 1})})
	w.Owner.Put(t, w.Path("/task-definitions/"+id), map[string]any{"name": "Daily"}).Expect(http.StatusOK).
		Match(taskDef(id, "Daily", agentID, map[string]any{"a": 1}))
	w.Owner.Put(t, w.Path("/task-definitions/"+id), map[string]any{"name": nil}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/task-definitions/"), map[string]any{"name": "x", "description": "d", "agent_id": agentID, "parameters": map[string]any{"session": "s"}}).
		Expect(http.StatusUnprocessableEntity)
	skipUnwired(t, w.Owner.Delete(t, w.Path("/task-definitions/"+id))).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/task-definitions/"+id)).Expect(http.StatusNotFound)
}
