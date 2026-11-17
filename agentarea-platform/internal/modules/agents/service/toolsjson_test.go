package service

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

func parse(t *testing.T, raw string) (domain.Tool, []httpx.FieldError) {
	t.Helper()
	v, err := wirejson.Unmarshal([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	var errs []httpx.FieldError
	tool, _ := ParseTool(v, []any{"body", "tools", 0}, &errs)
	return tool, errs
}

func TestToolRoundTrip(t *testing.T) {
	tool, errs := parse(t, `{"type":"mcp","name":" srv ","settings":{"allowed_tools":["a",{"tool_name":"b","requires_user_confirmation":true}],"junk":1}}`)
	if len(errs) != 0 {
		t.Fatal(errs)
	}
	stored, _ := wirejson.Marshal(ToolStored(tool), wirejson.Compact)
	want := `{"name":"srv","type":"mcp","settings":{"allowed_tools":[{"tool_name":"a"},{"tool_name":"b","requires_user_confirmation":true}]}}`
	if string(stored) != want {
		t.Errorf("stored %s", stored)
	}
	resp, _ := wirejson.Marshal(ToolResponse(tool), wirejson.Compact)
	wantResp := `{"name":"srv","type":"mcp","settings":{"requires_user_confirmation":null,"allowed_tools":[{"tool_name":"a","requires_user_confirmation":null},{"tool_name":"b","requires_user_confirmation":true}]}}`
	if string(resp) != wantResp {
		t.Errorf("response %s", resp)
	}
}

func TestToolErrors(t *testing.T) {
	for raw, typ := range map[string]string{
		`{"name":"x"}`:                "union_tag_not_found",
		`{"type":"nope","name":"x"}`:  "union_tag_invalid",
		`{"type":"code"}`:             "missing",
		`{"type":"code","name":"  "}`: "value_error",
		`{"type":"openapi","name":"x","settings":{"load_mode":"lazy"}}`:  "literal_error",
		`{"type":"code","name":"x","settings":{"disabled_methods":"a"}}`: "list_type",
		`5`: "model_attributes_type",
	} {
		_, errs := parse(t, raw)
		if len(errs) != 1 || errs[0].Type != typ {
			t.Errorf("%s: %v, want one %s", raw, errs, typ)
		}
	}
}

func TestStoredToolsLegacyShapes(t *testing.T) {
	if tools, isList := ParseStoredTools([]byte(`{"a":1}`)); tools != nil || isList {
		t.Error("a dict is read as no tools")
	}
	tools, isList := ParseStoredTools([]byte(`[{"type":"code","name":"a"},{"type":"zzz"},3]`))
	if !isList || len(tools) != 1 {
		t.Errorf("unparseable entries are skipped: %v", tools)
	}
}
