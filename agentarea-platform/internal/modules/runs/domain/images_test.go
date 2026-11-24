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
	if ids := ImagesToAttach(msgs, 2, ImageLimits{}); strings.Join(ids, ",") != "new,bad" {
		t.Fatalf("attach %v", ids)
	}
	out := AttachToolImages(msgs, map[string]*string{"new": &url, "bad": nil}, true, ImageLimits{})
	if len(out) != 4 || out[2].Role != "user" || out[2].Parts[0].Text != "Images returned by shot (call c1):" || out[2].Parts[1].ImageURL != url {
		t.Fatalf("messages %+v", out)
	}
	if want := "ok\n[image old from an earlier step is no longer attached]\n[image bad could not be loaded]"; out[1].Content != want {
		t.Fatalf("tool content %q", out[1].Content)
	}
	blind := AttachToolImages(msgs, nil, false, ImageLimits{})
	if len(blind) != 3 || !strings.Contains(blind[1].Content, "[image new not shown: this model does not read images]") {
		t.Fatalf("no vision %+v", blind)
	}
}

func TestAttachToolImagesLeavesOutWhatTheModelDoesNotTake(t *testing.T) {
	url := "data:image/png;base64,AA=="
	msgs := []ChatMessage{
		{Role: "assistant", ToolCalls: []ToolCall{{ID: "c1", Name: "read_file"}}},
		{Role: "tool", ToolCallID: "c1", Name: "read_file", Content: "ok", Attachments: []ImageRef{
			{ID: "heavy", Size: 12 << 20, Width: 4000, Height: 3000},
			{ID: "wide", Size: 1 << 20, Width: 9000, Height: 1000},
			{ID: "fits", Size: 1 << 20, Width: 2000, Height: 1500},
		}},
	}
	limits := ImageLimits{MaxBytes: 5 << 20, MaxEdge: 8000}
	if ids := ImagesToAttach(msgs, 8, limits); strings.Join(ids, ",") != "fits" {
		t.Fatalf("attach %v", ids)
	}
	out := AttachToolImages(msgs, map[string]*string{"fits": &url}, true, limits)
	want := "ok\n[image heavy not shown: 12.0 MB is over the 5.0 MB this model takes in one image; make a smaller copy " +
		"or crop the part you need in the shell, then read_file that]\n[image wide not shown: 9000x1000 px is over the " +
		"8000 px edge this model takes; make a smaller copy or crop the part you need in the shell, then read_file that]"
	if out[1].Content != want {
		t.Fatalf("tool content %q", out[1].Content)
	}
	if len(out) != 3 || len(out[2].Parts) != 2 || out[2].Parts[1].ImageURL != url {
		t.Fatalf("messages %+v", out)
	}
}

func TestAttachToolImagesSendsAPDFAsAFileWhereTheProviderReadsOne(t *testing.T) {
	pdf := "data:application/pdf;base64,JVBERi0="
	msgs := []ChatMessage{
		{Role: "assistant", ToolCalls: []ToolCall{{ID: "c1", Name: "read_file"}}},
		{Role: "tool", ToolCallID: "c1", Name: "read_file", Content: "ok", Attachments: []ImageRef{
			{ID: "old", MimeType: "application/pdf", Pages: 15},
			{ID: "plan", MimeType: "application/pdf", Pages: 10},
		}},
	}
	reads := ImageLimits{PDF: true}
	if ids := ImagesToAttach(msgs, 8, reads); strings.Join(ids, ",") != "plan" {
		t.Fatalf("attach %v, want only the newest PDF pages within %d", ids, MaxPDFPagesPerModelCall)
	}
	out := AttachToolImages(msgs, map[string]*string{"plan": &pdf}, true, reads)
	parts := out[2].Parts
	if len(parts) != 2 || parts[0].Text != "Files returned by read_file (call c1):" || parts[1] != (ContentPart{Type: "file", FileData: pdf, Filename: "plan.pdf"}) {
		t.Fatalf("parts %+v", parts)
	}
	if !strings.Contains(out[1].Content, "[file old from an earlier step is no longer attached]") {
		t.Fatalf("tool content %q", out[1].Content)
	}
	blind := AttachToolImages(msgs, nil, true, ImageLimits{})
	if len(blind) != 2 || !strings.Contains(blind[1].Content, "[file plan not shown: this model's provider does not read PDFs; render the pages you need to PNG with pdftoppm in the shell and read_file those]") {
		t.Fatalf("no PDF input %+v", blind)
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
