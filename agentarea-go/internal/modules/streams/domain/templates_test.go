package domain

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func decoded(t *testing.T, s string) any {
	t.Helper()
	var v any
	dec := json.NewDecoder(strings.NewReader(s))
	dec.UseNumber()
	if err := dec.Decode(&v); err != nil {
		t.Fatal(err)
	}
	return v
}

func templateContext(t *testing.T) TemplateContext {
	return TemplateContext{
		Body: decoded(t, `{"update_id": 81234, "message": {"chat": {"id": 555, "type": "private"}, "text": "hi",
			"photo": [{"id": "a"}]}, "action": null, "flag": false, "ratio": 1.50, "big": 12345678901234567890}`),
		Headers: map[string]string{"X-GitHub-Event": "push", "Request-Id": "r-1"},
	}
}

func mustRender(t *testing.T, tpl string, c TemplateContext) string {
	t.Helper()
	v, ok := Render(tpl, c)
	if !ok {
		t.Fatalf("%s rendered nothing", tpl)
	}
	return v
}

func TestTemplatesRenderPathsHeadersKeysAndConstants(t *testing.T) {
	c := templateContext(t)
	for tpl, want := range map[string]string{
		"{body:message.chat.id}":                            "555",
		"{body:message.photo.0.id}":                         "a",
		"{body:edited_message.chat.id|message.chat.id}":     "555",
		"{header:x-github-event}":                           "push",
		"{header:REQUEST-ID}":                               "r-1",
		"{first_key:edited_message|message|callback_query}": "message",
		"update:{body:update_id}":                           "update:81234",
		"{header:x-github-event}.{body:message.text}":       "push.hi",
		"message_received":                                  "message_received",
		"{body:flag}":                                       "false",
		"{body:ratio}":                                      "1.5",
		"{body:big}":                                        "12345678901234567890",
	} {
		if got := mustRender(t, tpl, c); got != want {
			t.Errorf("%s = %q, want %q", tpl, got, want)
		}
	}
}

func TestAMissingPlaceholderMakesTheFieldAbsent(t *testing.T) {
	c := templateContext(t)
	for _, tpl := range []string{"{header:x-github-event}.{body:action}", "{body:nope}", "{header:missing}",
		"{first_key:a|b}", "{query:x}", "{body:message}"} {
		if v, ok := Render(tpl, c); ok {
			t.Errorf("%s rendered %q", tpl, v)
		}
	}
}

func TestTheFirstTemplateThatRendersWins(t *testing.T) {
	c := templateContext(t)
	if v, _ := RenderFirst(Template{"{header:x-github-event}.{body:action}", "{header:x-github-event}"}, c); v != "push" {
		t.Fatalf("got %q", v)
	}
	if _, ok := RenderFirst(Template{"{body:nope}"}, c); ok {
		t.Fatal("rendered")
	}
	if _, ok := RenderFirst(nil, c); ok {
		t.Fatal("rendered")
	}
}

func TestRenderValueKeepsTypesAndDropsMissingLeaves(t *testing.T) {
	c := TemplateContext{Values: map[string]any{"target": map[string]any{"chat_id": json.Number("555")}, "message": "hello"}}
	got := RenderValue(map[string]any{"chat_id": "{target:chat_id}", "text": "{message}", "reply": "{target:message_id}"}, c)
	want := map[string]any{"chat_id": json.Number("555"), "text": "hello"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %#v", got)
	}
	c = TemplateContext{Values: map[string]any{"message": "hi", "target": map[string]any{}}}
	got = RenderValue(map[string]any{"content": "{message}", "message_reference": map[string]any{"message_id": "{target:message_id}"}}, c)
	if !reflect.DeepEqual(got, map[string]any{"content": "hi"}) {
		t.Fatalf("got %#v", got)
	}
}

func TestRenderURLEscapesEachValueAsOneSegment(t *testing.T) {
	c := TemplateContext{Body: map[string]any{"id": "a/b c?"}}
	if v, _ := RenderURL("https://x.example/v1/{body:id}", c); v != "https://x.example/v1/a%2Fb%20c%3F" {
		t.Fatalf("got %q", v)
	}
}

func TestPyFloatIsPythonRepr(t *testing.T) {
	for f, want := range map[float64]string{1.5: "1.5", 2: "2.0", 1e16: "1e+16", 1e-5: "1e-05", 0.0001: "0.0001", 123456789012345.0: "123456789012345.0"} {
		if got := PyFloat(f); got != want {
			t.Errorf("PyFloat(%v) = %q, want %q", f, got, want)
		}
	}
}
