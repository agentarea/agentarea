package domain

import (
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

func TestAnOffloadedOutputIsATaskInputFileNamedByItsContent(t *testing.T) {
	for content, want := range map[string]string{
		`{"items": [1, 2]}`:  "inputs/tool-outputs/call_1.json",
		"[1, 2]":             "inputs/tool-outputs/call_1.json",
		"total 4\nfile.txt":  "inputs/tool-outputs/call_1.txt",
		"{\"cut\": [1, 2":    "inputs/tool-outputs/call_1.txt",
		"[image 2 not kept]": "inputs/tool-outputs/call_1.txt",
	} {
		if got := ToolOutputPath("call_1", content); got != want {
			t.Errorf("ToolOutputPath(%.20q) = %q, want %q", content, got, want)
		}
	}
}

func TestOutputSummaryPointsAtTheFileAndReadFile(t *testing.T) {
	content := strings.Repeat("line\n", 2000)
	got := OutputSummary(content, "inputs/tool-outputs/call_1.txt")
	if !strings.HasPrefix(got, "[Output stored in inputs/tool-outputs/call_1.txt — 10,000 chars, 2001 lines]\nPreview:\nline") ||
		!strings.Contains(got, `read_file("inputs/tool-outputs/call_1.txt"`) || strings.Contains(got, "read_tool_output") {
		t.Fatalf("summary %q", got)
	}
}

func TestOnlyTheBuiltInReadFileBindingIsReadFile(t *testing.T) {
	if !IsReadFile(ToolReadFile, ReadFileBinding()) {
		t.Fatal("the built-in read_file is not read_file")
	}
	mcp := api.ToolBinding{Source: "mcp", MCP: &api.MCPBinding{InstanceID: "i1", RawName: ToolReadFile}}
	if IsReadFile(ToolReadFile, mcp) || IsReadFile(ToolReadFile, api.ToolBinding{}) || IsReadFile("files_save_file", ReadFileBinding()) {
		t.Fatal("another tool passes as the built-in read_file")
	}
}
