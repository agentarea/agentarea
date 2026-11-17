package domain

import (
	"strings"
	"testing"
)

func TestAttachToolImagesShowsTheNewestAndNamesTheRest(t *testing.T) {
	url := "data:image/png;base64,AA=="
	msgs := []ChatMessage{
		{Role: "assistant", ToolCalls: []ToolCall{{ID: "c1", Name: "shot"}}},
		{Role: "tool", ToolCallID: "c1", Name: "shot", Content: "ok", Attachments: []ImageRef{{ID: "old"}, {ID: "new"}, {ID: "bad"}}},
		{Role: "user", Content: "next"},
	}
	if ids := ImagesToAttach(msgs, 2); strings.Join(ids, ",") != "new,bad" {
		t.Fatalf("attach %v", ids)
	}
	out := AttachToolImages(msgs, map[string]*string{"new": &url, "bad": nil}, true)
	if len(out) != 4 || out[2].Role != "user" || out[2].Parts[0].Text != "Images returned by shot (call c1):" || out[2].Parts[1].ImageURL != url {
		t.Fatalf("messages %+v", out)
	}
	if want := "ok\n[image old from an earlier step is no longer attached]\n[image bad could not be loaded]"; out[1].Content != want {
		t.Fatalf("tool content %q", out[1].Content)
	}
	blind := AttachToolImages(msgs, nil, false)
	if len(blind) != 3 || !strings.Contains(blind[1].Content, "[image new not shown: this model does not read images]") {
		t.Fatalf("no vision %+v", blind)
	}
}

func TestAgentConfigHashIgnoresToolOrder(t *testing.T) {
	a := []any{map[string]any{"type": "mcp", "name": "a"}, map[string]any{"type": "code", "name": "b"}}
	b := []any{a[1], a[0]}
	h1 := AgentConfigHash("be kind", "m1", a, false, "", []string{"s2", "s1"})
	if h2 := AgentConfigHash("be kind", "m1", b, false, "", []string{"s1", "s2"}); h1 != h2 || !strings.HasPrefix(h1, "v2:") {
		t.Fatalf("%s != %s", h1, h2)
	}
	if AgentConfigHash("be kind", "m2", a, false, "", nil) == h1 {
		t.Fatal("a different model hashes the same")
	}
}
