package handlers

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

func decode(t *testing.T, body string) any {
	t.Helper()
	v, err := wirejson.Unmarshal([]byte(body))
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestCreateBodyReportsEveryError(t *testing.T) {
	var in input
	var errs []httpx.FieldError
	createBody(decode(t, `{"name":"","tools":"x","nope":1,"reasoning_effort":"BAD","agent_type":"x"}`), &in, &errs)
	types := map[string]bool{}
	for _, e := range errs {
		types[e.Type] = true
	}
	for _, want := range []string{"string_too_short", "list_type", "extra_forbidden", "value_error", "literal_error"} {
		if !types[want] {
			t.Errorf("missing %s in %v", want, errs)
		}
	}
}

func TestCreateBodyAcceptsAMinimalAgent(t *testing.T) {
	var in input
	var errs []httpx.FieldError
	createBody(decode(t, `{"name":"  Helper ","tools":[],"reasoning_max_tokens":5}`), &in, &errs)
	if len(errs) != 0 {
		t.Fatal(errs)
	}
	c := in.create
	if c.Name != "Helper" || c.AgentType != "stateless" || c.Description != "" || *c.ReasoningMaxTokens != 5 || c.Tools == nil {
		t.Errorf("%+v", c)
	}
}

func TestUpdateBodyTellsAbsentFromNull(t *testing.T) {
	var in input
	var errs []httpx.FieldError
	updateBody(decode(t, `{"description":null,"planning":true}`), &in, &errs)
	if len(errs) != 0 {
		t.Fatal(errs)
	}
	p := in.patch
	if !p.Description.Set || p.Description.Value != nil || p.Instruction.Set || !p.Planning.Set || p.Tools != nil {
		t.Errorf("%+v", p)
	}
	errs = nil
	updateBody(decode(t, `{"name":null,"agent_type":null}`), &in, &errs)
	if len(errs) != 2 {
		t.Errorf("name and agent_type may not be null: %v", errs)
	}
}

func TestResponseTools(t *testing.T) {
	for raw, want := range map[string]string{"": "null", "[]": "null", "{}": "null", `{"a":1}`: "[]"} {
		b, _ := wirejson.Marshal(toolsJSON([]byte(raw), nil), wirejson.Compact)
		if string(b) != want {
			t.Errorf("toolsJSON(%q) = %s, want %s", raw, b, want)
		}
	}
}

func TestVisitWritesCompactJSON(t *testing.T) {
	rec := httptest.NewRecorder()
	if err := ok(wirejson.Object{{Key: "status", Value: "success"}}).visit(rec); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK || strings.TrimSpace(rec.Body.String()) != `{"status":"success"}` {
		t.Errorf("%d %s", rec.Code, rec.Body)
	}
}
