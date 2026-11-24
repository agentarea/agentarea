package domain

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestClientAttachableToolset(t *testing.T) {
	for ref, want := range map[string]string{"runs": "agentarea/runs", "agentarea/runs": "agentarea/runs"} {
		if got, err := ClientAttachableToolset(ref, []string{"cancel"}); err != nil || got != want {
			t.Errorf("%s: %q %v", ref, got, err)
		}
	}
	_, err := ClientAttachableToolset("nope", nil)
	if err == nil || !strings.HasPrefix(err.Error(), "Unknown toolset 'nope'. Available: agents, runs, task_definitions, ") ||
		!strings.HasSuffix(err.Error(), ", network, workspace_config") {
		t.Errorf("%v", err)
	}
	_, err = ClientAttachableToolset("runs", []string{"zz", "aa", "zz", "cancel"})
	if err == nil || err.Error() != "Toolset 'agentarea/runs' has no method(s) aa, zz" {
		t.Errorf("%v", err)
	}
}

func TestClientPlatformToolsetsAreSorted(t *testing.T) {
	all := ClientPlatformToolsets()
	if len(all) != 23 {
		t.Fatalf("%d toolsets", len(all))
	}
	for _, ts := range all {
		for i := 1; i < len(ts.Methods); i++ {
			if ts.Methods[i-1].Name >= ts.Methods[i].Name {
				t.Errorf("%s methods out of order", ts.Namespace)
			}
		}
	}
}

func TestClientCheckDomains(t *testing.T) {
	for _, ok := range []string{"pypi.org", "*.githubusercontent.com", "LOCALHOST", "a-b.c1", "x.org\n"} {
		if msg := ClientCheckDomains([]string{ok}); msg != "" {
			t.Errorf("%q: %s", ok, msg)
		}
	}
	for in, want := range map[string]string{
		"-a.org": `not a host name: '-a.org'`, "a b": `not a host name: 'a b'`, "it's": `not a host name: "it's"`,
		"a\tb": `not a host name: 'a\tb'`, "*.": `not a host name: '*.'`, strings.Repeat("a", 254): "not a host name: '" + strings.Repeat("a", 254) + "'",
	} {
		if got := ClientCheckDomains([]string{"ok.org", in}); got != want {
			t.Errorf("%q: %s, want %s", in, got, want)
		}
	}
}

func TestTaskDefCheckParameters(t *testing.T) {
	cases := map[string]string{
		`{}`:                                 "",
		`{"session":1,"delivery_address":2}`: "delivery_address, session is set by the trigger that received the event and cannot be supplied",
		`{"model_override":""}`:              "",
		`{"model_override":5}`:               "model_override must be a model instance id",
		`{"model_override":"x"}`:             "model_override must be a model instance id",
		`{"model_override":"{12345678123456781234567812345678}"}`:      "",
		`{"reasoning_effort":"High"}`:                                  "reasoning_effort must be a level name such as low or high",
		`{"reasoning_max_tokens":-1}`:                                  "reasoning_max_tokens must be a positive integer",
		`{"reasoning_effort":"low","reasoning_max_tokens":0}`:          "reasoning_max_tokens must be a positive integer",
		`{"reasoning_effort":"low","reasoning_max_tokens":1.0}`:        "reasoning_max_tokens must be a positive integer",
		`{"reasoning_effort":"low","reasoning_max_tokens":3000000000}`: "reasoning_max_tokens must be at most 2147483647",
		`{"reasoning_effort":"low","reasoning_max_tokens":5}`:          "set reasoning_effort or reasoning_max_tokens, not both",
		`{"reasoning_effort":"low","reasoning_max_tokens":null}`:       "",
	}
	for raw, want := range cases {
		dec := json.NewDecoder(strings.NewReader(raw))
		dec.UseNumber()
		var m map[string]any
		if err := dec.Decode(&m); err != nil {
			t.Fatal(err)
		}
		if f, ok := m["reasoning_max_tokens"].(json.Number); ok && strings.Contains(string(f), ".") {
			m["reasoning_max_tokens"] = 1.0
		}
		keys := make([]string, 0, len(m))
		for k := range m {
			keys = append(keys, k)
		}
		got := TaskDefCheckParameters(keys, func(k string) (any, bool) { v, ok := m[k]; return v, ok })
		if got != want {
			t.Errorf("%s: %q, want %q", raw, got, want)
		}
	}
}

func TestTaskDefPythonUUID(t *testing.T) {
	for s, ok := range map[string]bool{
		"12345678-1234-5678-1234-567812345678": true, "urn:uuid:12345678123456781234567812345678": true,
		"1234-5678123456781234567812345678": true, "1234567812345678123456781234567g": false, "": false,
	} {
		if TaskDefPythonUUID(s) != ok {
			t.Errorf("%q != %v", s, ok)
		}
	}
}

func TestTaskDefISOZ(t *testing.T) {
	if got := TaskDefISOZ(time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)); got != "2026-01-02T03:04:05Z" {
		t.Error(got)
	}
	if got := TaskDefISOZ(time.Date(2026, 1, 2, 3, 4, 5, 42000, time.UTC)); got != "2026-01-02T03:04:05.000042Z" {
		t.Error(got)
	}
}
