package handlers_test

import (
	"net/http"
	"testing"

	"github.com/google/uuid"
)

func TestTriggerReadRoutes(t *testing.T) {
	g := newRig(t)
	rec := g.do(http.MethodPost, "/", cronBody(g.agent))
	if rec.Code != http.StatusCreated {
		t.Fatalf("create = %d %s", rec.Code, rec.Body)
	}
	id := decode(t, rec)["id"].(string)

	rec = g.do(http.MethodGet, "/"+id+"/executions?page_size=10&status=success", nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("executions = %d %s", rec.Code, rec.Body)
	}
	if m := decode(t, rec); m["total"] != float64(0) || m["page_size"] != float64(10) || m["has_next"] != false {
		t.Fatalf("executions body = %v", m)
	}
	if rec = g.do(http.MethodGet, "/"+id+"/executions?status=nope", nil); rec.Code != http.StatusBadRequest {
		t.Fatalf("bad status = %d %s", rec.Code, rec.Body)
	}
	if rec = g.do(http.MethodGet, "/"+id+"/executions?page_size=101", nil); rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("page_size 101 = %d %s", rec.Code, rec.Body)
	}

	rec = g.do(http.MethodGet, "/"+id+"/metrics", nil)
	if m := decode(t, rec); rec.Code != http.StatusOK || m["period_hours"] != nil || m["total_cost_usd"] != float64(0) {
		t.Fatalf("metrics = %d %v", rec.Code, m)
	}
	if rec = g.do(http.MethodGet, "/"+id+"/metrics?hours=9000", nil); rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("hours 9000 = %d", rec.Code)
	}
	rec = g.do(http.MethodGet, "/"+id+"/timeline?hours=48&bucket_size_minutes=15", nil)
	if m := decode(t, rec); rec.Code != http.StatusOK || m["period_hours"] != float64(48) {
		t.Fatalf("timeline = %d %v", rec.Code, m)
	}
	if rec = g.do(http.MethodGet, "/"+id+"/timeline?bucket_size_minutes=1", nil); rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("bucket 1 = %d", rec.Code)
	}
	rec = g.do(http.MethodGet, "/"+id+"/correlations", nil)
	if m := decode(t, rec); rec.Code != http.StatusOK || m["page"] != float64(1) {
		t.Fatalf("correlations = %d %v", rec.Code, m)
	}
	rec = g.do(http.MethodGet, "/"+id+"/status", nil)
	m := decode(t, rec)
	if rec.Code != http.StatusOK || m["is_active"] != true || m["should_disable_due_to_failures"] != false {
		t.Fatalf("status = %d %v", rec.Code, m)
	}
	if info, ok := m["schedule_info"].(map[string]any); !ok || info["schedule_id"] != "cron-trigger-"+id {
		t.Fatalf("schedule_info = %v", m["schedule_info"])
	}
	if rec = g.do(http.MethodGet, "/"+uuid.NewString()+"/status", nil); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown status = %d", rec.Code)
	}
	rec = g.do(http.MethodGet, "/health", nil)
	if m := decode(t, rec); rec.Code != http.StatusOK || m["service"] != "triggers" || m["overall_status"] != "healthy" {
		t.Fatalf("health = %d %v", rec.Code, m)
	}
}

func TestUpdateNullClearsAndAbsentKeeps(t *testing.T) {
	g := newRig(t)
	body := cronBody(g.agent)
	td := uuid.NewString()
	body["task_definition_id"] = td
	rec := g.do(http.MethodPost, "/", body)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create = %d %s", rec.Code, rec.Body)
	}
	id := decode(t, rec)["id"].(string)
	rec = g.do(http.MethodPut, "/"+id, map[string]any{"name": "renamed"})
	if m := decode(t, rec); rec.Code != http.StatusOK || m["task_definition_id"] != td {
		t.Fatalf("absent should keep: %d %v", rec.Code, m)
	}
	rec = g.do(http.MethodPut, "/"+id, map[string]any{"task_definition_id": nil})
	if m := decode(t, rec); rec.Code != http.StatusOK || m["task_definition_id"] != nil {
		t.Fatalf("null should clear: %d %v", rec.Code, m)
	}
	rec = g.do(http.MethodPut, "/"+id, map[string]any{"is_active": false})
	if m := decode(t, rec); rec.Code != http.StatusOK || m["is_active"] != false {
		t.Fatalf("is_active alias: %d %v", rec.Code, m)
	}
	rec = g.do(http.MethodPut, "/"+id, map[string]any{"cron_expression": "0 9 * * 1-5 2030"})
	if m := decode(t, rec); rec.Code != http.StatusOK || m["cron_expression"] != "0 9 * * 1-5 2030" {
		t.Fatalf("six field cron: %d %v", rec.Code, m)
	}
}
