package domain

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func a2aRender(t *testing.T, v any) string {
	t.Helper()
	var b strings.Builder
	var walk func(v any)
	walk = func(v any) {
		switch x := v.(type) {
		case A2AJSON:
			b.WriteByte('{')
			for i, m := range x {
				if i > 0 {
					b.WriteByte(',')
				}
				k, _ := json.Marshal(m.Key)
				b.Write(k)
				b.WriteByte(':')
				walk(m.Value)
			}
			b.WriteByte('}')
		case []any:
			b.WriteByte('[')
			for i, e := range x {
				if i > 0 {
					b.WriteByte(',')
				}
				walk(e)
			}
			b.WriteByte(']')
		case float64:
			b.WriteString(a2aPyFloat(x))
		default:
			raw, err := json.Marshal(x)
			if err != nil {
				t.Fatal(err)
			}
			b.Write(raw)
		}
	}
	walk(v)
	return b.String()
}

func a2aDecode(t *testing.T, raw string) any {
	t.Helper()
	dec := json.NewDecoder(strings.NewReader(raw))
	dec.UseNumber()
	var walk func() any
	walk = func() any {
		tok, err := dec.Token()
		if err != nil {
			t.Fatal(err)
		}
		switch x := tok.(type) {
		case json.Delim:
			if x == '{' {
				o := A2AJSON{}
				for dec.More() {
					k, _ := dec.Token()
					o.Set(k.(string), walk())
				}
				_, _ = dec.Token()
				return o
			}
			l := []any{}
			for dec.More() {
				l = append(l, walk())
			}
			_, _ = dec.Token()
			return l
		}
		return tok
	}
	return walk()
}

func ptrTo[T any](v T) *T { return &v }

func TestA2ACardMatchesMessageToDict(t *testing.T) {
	a := Agent{ID: "7d1c1b9e-3c2a-4f7e-9a51-0e7d2f3b4c5d", Name: "Helper", Tools: []byte(`[{"tool_type":"mcp"}]`),
		Planning: ptrTo(true), A2UIEnabled: ptrTo(true)}
	rpc := "https://API.example.com:8443/v1/agents/" + a.ID + "/a2a/rpc"
	want := `{"name":"Helper","description":"AI agent Helper","supportedInterfaces":[{"url":"` + rpc + `","protocolBinding":"JSONRPC","protocolVersion":"1.0"}],` +
		`"provider":{"url":"https://API.example.com:8443","organization":"AgentArea"},"version":"1.0.0",` +
		`"capabilities":{"streaming":true,"pushNotifications":true,"extensions":[{"uri":"https://a2ui.org/a2a-extension/a2ui/v0.9","params":{"supportedCatalogIds":["https://a2ui.org/specification/v0_9/basic_catalog.json"]}}],"extendedAgentCard":true},` +
		`"securitySchemes":{"bearer":{"httpAuthSecurityScheme":{"scheme":"bearer"}}},"securityRequirements":[{"schemes":{"bearer":{}}}],` +
		`"defaultInputModes":["text/plain","application/json"],"defaultOutputModes":["text/plain","application/json"],` +
		`"skills":[{"id":"text-processing","name":"Text Processing","description":"Process and respond to text messages using Helper","tags":["text","chat"],"inputModes":["text/plain"],"outputModes":["text/plain"]}`
	if got := a2aRender(t, A2ACard(a, rpc, false)); got != want+`]}` {
		t.Errorf("public card\n got %s\nwant %s]}", got, want)
	}
	ext := a2aRender(t, A2ACard(a, rpc, true))
	if !strings.Contains(ext, `{"id":"tool-execution","name":"Tool Execution","description":"Execute tools and integrations using Helper","tags":["tools","integration"],"inputModes":["text/plain"],"outputModes":["text/plain","application/json"]},{"id":"task-planning"`) {
		t.Errorf("extended card %s", ext)
	}
	a.Description, a.A2UIEnabled, a.Tools = ptrTo("Answers"), nil, []byte(`{}`)
	plain := a2aRender(t, A2ACard(a, rpc, true))
	if !strings.Contains(plain, `"description":"Answers"`) || strings.Contains(plain, "extensions") || strings.Contains(plain, "tool-execution") {
		t.Errorf("%s", plain)
	}
}

func TestA2AURLs(t *testing.T) {
	id := "7d1c1b9e-3c2a-4f7e-9a51-0e7d2f3b4c5d"
	tmpl := "https://{agent_id}.a2a.example.com/"
	if got := A2AHostRPCURL(tmpl, id); got != "https://"+id+".a2a.example.com/" {
		t.Error(got)
	}
	if got := A2AAPIRPCURL("http://api/", id); got != "http://api/v1/agents/"+id+"/a2a/rpc" {
		t.Error(got)
	}
	for host, want := range map[string]string{
		id + ".a2a.example.com": id,
		strings.ToUpper("7d1c1b9e3c2a4f7e9a510e7d2f3b4c5d") + ".a2a.example.com:443": id,
		"agent.a2a.example.com":        "",
		id + ".a2a.example.org":        "",
		"x." + id + ".a2a.example.com": "",
		"api.example.com":              "",
	} {
		got, ok := A2AHostAgent(tmpl, host)
		if got != want || ok != (want != "") {
			t.Errorf("%s: %q %v", host, got, ok)
		}
	}
	for in, want := range map[string]string{
		" https://peer.example/.well-known/agent-card.json ": "https://peer.example",
		"https://peer.example//":                             "https://peer.example",
	} {
		if got := A2ACardAddress(in); got != want {
			t.Errorf("%q: %q", in, got)
		}
	}
}

func TestA2AFrame(t *testing.T) {
	for raw, want := range map[string]string{
		`[]`:                                    `{"error":{"code":-32600,"message":"Invalid Request","data":"[] value is not accepted"},"id":null,"jsonrpc":"2.0"}`,
		`5`:                                     `{"error":{"code":-32600,"message":"Invalid Request","data":"Each request should be an object (dict)"},"id":null,"jsonrpc":"2.0"}`,
		`[{"jsonrpc":"2.0","method":"a"}]`:      `{"error":{"code":-32600,"message":"Batch requests are not supported"},"id":null,"jsonrpc":"2.0"}`,
		`{"id":3,"method":"x","x":1,"y":2}`:     `{"error":{"code":-32600,"message":"Invalid Request","data":"Invalid request. Extra fields: {'x', 'y'}, Missed fields: {'jsonrpc'}"},"id":3,"jsonrpc":"2.0"}`,
		`{"jsonrpc":"2.0","method":1,"id":"a"}`: `{"error":{"code":-32600,"message":"Invalid Request","data":"Method should be string"},"id":"a","jsonrpc":"2.0"}`,
		`{"jsonrpc":"2.0","method":"m","params":7}`: `{"error":{"code":-32600,"message":"Invalid Request","data":"Incorrect params 7"},"id":null,"jsonrpc":"2.0"}`,
		`{"jsonrpc":"2.0","method":"m","id":1.5}`:   `{"error":{"code":-32600,"message":"Invalid Request","data":"id should be string or integer"},"id":null,"jsonrpc":"2.0"}`,
		`{"jsonrpc":"1.0","method":"m","id":2}`:     `{"error":{"code":-32600,"message":"Invalid request: 'jsonrpc' must be exactly '2.0'"},"id":2,"jsonrpc":"2.0"}`,
		`{"jsonrpc":"2.0","method":"","id":2}`:      `{"error":{"code":-32600,"message":"Method is required"},"id":2,"jsonrpc":"2.0"}`,
	} {
		_, failure := A2AFrame(a2aDecode(t, raw))
		if got := a2aRender(t, failure); got != want {
			t.Errorf("%s\n got %s\nwant %s", raw, got, want)
		}
	}
	req, failure := A2AFrame(a2aDecode(t, `{"jsonrpc":"2.0","method":"GetTask","id":"r1","params":{"id":"t"}}`))
	if failure != nil || req.Method != "GetTask" || req.ID != "r1" || !req.HasParams {
		t.Fatalf("%+v %v", req, failure)
	}
}

func TestA2AParseParams(t *testing.T) {
	for _, c := range []struct{ method, params, want string }{
		{"GetExtendedAgentCard", `{}`, ""},
		{"GetExtendedAgentCard", `{"tenant":null}`, ""},
		{"GetTask", `{"history_length":3,"id":"t"}`, ""},
		{"GetExtendedAgentCard", `{"nope":1}`, "Message type \"lf.a2a.v1.GetExtendedAgentCardRequest\" has no field named \"nope\" at \"GetExtendedAgentCardRequest\".\n Available Fields(except extensions): \"['tenant']\""},
		{"GetExtendedAgentCard", `{"tenant":5}`, "Failed to parse tenant field: expected string or bytes-like object, got 'int'."},
		{"GetExtendedAgentCard", `null`, "'NoneType' object is not iterable"},
		{"GetExtendedAgentCard", `["tenant"]`, "Failed to parse tenant field: list indices must be integers or slices, not str."},
		{"GetExtendedAgentCard", `[]`, ""},
		{"SubscribeToTask", `{"[x]":1}`, "Message type lf.a2a.v1.SubscribeToTaskRequest does not have extensions at SubscribeToTaskRequest"},
	} {
		got := ""
		if e := A2AParseParams(c.method, a2aDecode(t, c.params), true); e != nil {
			got = e.Data.(string)
		}
		if got != c.want {
			t.Errorf("%s %s\n got %q\nwant %q", c.method, c.params, got, c.want)
		}
	}
}

func TestA2ACheckVersion(t *testing.T) {
	for v, ok := range map[string]bool{"1.0": true, "1": true, "1.2.3": true, " v1.1rc1 ": true, "": false, "0.3": false, "2.0": false, "abc": false} {
		if got := A2ACheckVersion(v) == nil; got != ok {
			t.Errorf("%q: %v", v, got)
		}
	}
	e := A2ACheckVersion("")
	if a2aRender(t, e.JSON()) != `{"code":-32009,"message":"A2A version '0.3' is not supported by this handler. Expected version '1.0'.","data":[{"@type":"type.googleapis.com/google.rpc.ErrorInfo","reason":"VERSION_NOT_SUPPORTED","domain":"a2a-protocol.org","metadata":{}}]}` {
		t.Error(a2aRender(t, e.JSON()))
	}
}

func TestA2ATask(t *testing.T) {
	at := time.Date(2026, 1, 2, 3, 4, 5, 120_000_000, time.UTC)
	row := A2ATaskRow{ID: "t1", Status: "completed", Result: a2aDecode(t, `{"response":"  ","text":"Done"}`),
		Metadata: a2aDecode(t, `{"a2a_context_id":"c1","n":3}`).(A2AJSON), UpdatedAt: &at}
	want := `{"id":"t1","contextId":"c1","status":{"state":"TASK_STATE_COMPLETED","message":{"messageId":"t1-status","role":"ROLE_AGENT","parts":[{"text":"Done"}]},"timestamp":"2026-01-02T03:04:05.120Z"},` +
		`"artifacts":[{"artifactId":"t1","name":"agent-response","parts":[{"text":"Done"}]}],"metadata":{"a2a_context_id":"c1","n":3.0}}`
	if got := a2aRender(t, A2ATask(row, at)); got != want {
		t.Errorf("\n got %s\nwant %s", got, want)
	}
	row = A2ATaskRow{ID: "t2", Status: "mystery", UpdatedAt: &at}
	if got := a2aRender(t, A2ATask(row, at)); got != `{"id":"t2","contextId":"t2","status":{"timestamp":"2026-01-02T03:04:05.120Z"}}` {
		t.Error(got)
	}
	failed := A2ATaskRow{ID: "t3", Status: "blocked", ErrorMessage: ptrTo("boom")}
	if got := a2aRender(t, A2ATask(failed, at)); !strings.Contains(got, `"state":"TASK_STATE_FAILED","message":{"messageId":"t3-status","role":"ROLE_AGENT","parts":[{"text":"boom"}]}`) {
		t.Error(got)
	}
}

func TestA2ABuildTask(t *testing.T) {
	now := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	got := A2ABuildTask(A2AMessageIn{
		Parts:          []A2APart{{Kind: "text", Text: "  Hello\nworld "}, {Kind: "data"}},
		ContextID:      "ctx",
		ClientMetadata: a2aDecode(t, `{"source":"spoof","a2a_agent_key_id":"forged","requires_human_approval":true}`).(A2AJSON),
		AgentID:        "a1",
		Auth: A2AAuth{Authenticated: true, AuthMethod: "bearer", Permissions: []string{"agent:execute"}, AgentKeyID: "k1",
			Metadata: A2AJSON{{Key: "user_agent", Value: "curl"}, {Key: "client_ip", Value: nil}, {Key: "agent_name", Value: "Helper"}}},
		UserID: "u1", WorkspaceID: "w1", Method: "SendMessage", RequestID: "r1", Now: now,
	})
	if got.Title != "Hello" || got.Description != "Hello\nworld" || got.Query != "  Hello\nworld " || got.Status != "submitted" {
		t.Errorf("%+v", got)
	}
	md := a2aRender(t, got.Metadata)
	for _, want := range []string{
		`{"source":"a2a","requires_human_approval":true,"a2a_method":"SendMessage","a2a_request_id":"r1"`,
		`"created_timestamp":"2026-01-02T03:04:05+00:00"`,
		`"monitoring":{"task_source":"a2a_protocol","protocol_version":"1.0","message_length":14,"has_message_parts":true,"message_parts_count":2,"is_streaming":false,"agent_target":"a1"}`,
		`"a2a_agent_key_id":"k1","a2a_context_id":"ctx","target_agent_name":"Helper","client_metadata":{"user_agent":"curl"}}`,
	} {
		if !strings.Contains(md, want) {
			t.Errorf("metadata %s\nmissing %s", md, want)
		}
	}
	empty := A2ABuildTask(A2AMessageIn{Now: now})
	if empty.Title != "A2A Message Task" || empty.Description != "Task created from A2A message" {
		t.Errorf("%+v", empty)
	}
}

func TestA2AWorkflowEvent(t *testing.T) {
	at := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	s := A2AStream{TaskID: "t", ContextID: "c", Now: at, NewID: func() string { return "m" }}
	ts := `"timestamp":"2026-01-02T03:04:05Z"`
	for _, c := range []struct {
		typ, data string
		want      []string
		done      bool
	}{
		{"workflow.task.completed", `{"original_data":{"result":"42"}}`, []string{
			`{"artifactUpdate":{"taskId":"t","contextId":"c","artifact":{"artifactId":"t","name":"agent-response","parts":[{"text":"42"}]},"lastChunk":true}}`,
			`{"statusUpdate":{"taskId":"t","contextId":"c","status":{"state":"TASK_STATE_COMPLETED",` + ts + `}}}`,
		}, true},
		{"task.failed", `{"result":"x"}`, []string{`{"statusUpdate":{"taskId":"t","contextId":"c","status":{"state":"TASK_STATE_FAILED",` + ts + `}}}`}, true},
		{"approval.requested", `{"tool_name":"shell"}`, []string{
			`{"statusUpdate":{"taskId":"t","contextId":"c","status":{"state":"TASK_STATE_INPUT_REQUIRED","message":{"messageId":"m","role":"ROLE_AGENT","parts":[{"text":"Waiting for approval to run shell"}]},` + ts + `},"metadata":{"agentarea_event":"approval.requested"}}}`,
		}, true},
		{"llm.call.chunk", `{"chunk":"par"}`, []string{
			`{"artifactUpdate":{"taskId":"t","contextId":"c","artifact":{"artifactId":"t","name":"agent-response","parts":[{"text":"par"}]}}}`,
		}, false},
		{"llm.call.chunk", `{}`, nil, false},
		{"turn.started", `{"iteration":2}`, []string{
			`{"statusUpdate":{"taskId":"t","contextId":"c","status":{"state":"TASK_STATE_WORKING","message":{"messageId":"m","role":"ROLE_AGENT","parts":[{"text":"Step 2"}]},` + ts + `},"metadata":{"agentarea_event":"turn.started"}}}`,
		}, false},
		{"tool.result", `{"tool_name":"web","success":false}`, []string{`"text":"web failed"`}, false},
		{"something.else", `{}`, []string{`{"statusUpdate":{"taskId":"t","contextId":"c","status":{"state":"TASK_STATE_WORKING",` + ts + `}}}`}, false},
	} {
		events, done := s.A2AWorkflowEvent(c.typ, a2aDecode(t, c.data).(A2AJSON))
		if done != c.done || len(events) != len(c.want) {
			t.Errorf("%s: done %v events %d", c.typ, done, len(events))
			continue
		}
		for i, e := range events {
			if got := a2aRender(t, e); !strings.Contains(got, c.want[i]) {
				t.Errorf("%s\n got %s\nwant %s", c.typ, got, c.want[i])
			}
		}
	}
}

func TestA2APyRepr(t *testing.T) {
	for v, want := range map[float64]string{1e16: "1e+16", 1e6: "1000000.0", 0.0001: "0.0001", 1.5e-5: "1.5e-05", 3: "3.0"} {
		if got := a2aPyFloat(v); got != want {
			t.Errorf("%v: %s", v, got)
		}
	}
	if got := a2aPyRepr(A2AJSON{{Key: "a", Value: []any{true, nil, "it's"}}}); got != `{'a': [True, None, "it's"]}` {
		t.Error(got)
	}
}
