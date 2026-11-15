package service

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

func miscJSON(t *testing.T, s string) any {
	t.Helper()
	v, err := wirejson.Unmarshal([]byte(s))
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestToolsMCPJSON(t *testing.T) {
	inst := ToolsMCPInstance{ID: "i", Name: "N"}
	cases := []struct {
		tool, want string
		malformed  bool
	}{
		{`{"name":"a","description":"d","inputSchema":{"type":"object"}}`, `{"name":"a","type":"mcp","description":"d","display_name":"","category":"","plane":null,"group":null,"requires_user_confirmation":false,"available_methods":[],"input_schema":{"type":"object"},"mcp_instance_id":"i","mcp_instance_name":"N"}`, false},
		{`{"function":{"name":"b","parameters":{"x":1}},"name":"ignored"}`, `{"name":"b","type":"mcp","description":"MCP tool: b","display_name":"","category":"","plane":null,"group":null,"requires_user_confirmation":false,"available_methods":[],"input_schema":{"x":1},"mcp_instance_id":"i","mcp_instance_name":"N"}`, false},
		{`{"function":"x","name":"c","parameters":{},"inputSchema":{"y":2}}`, `{"name":"c","type":"mcp","description":"MCP tool: c","display_name":"","category":"","plane":null,"group":null,"requires_user_confirmation":false,"available_methods":[],"input_schema":{"y":2},"mcp_instance_id":"i","mcp_instance_name":"N"}`, false},
		{`{"description":"no name"}`, ``, false},
		{`{"name":0}`, ``, false},
		{`{"name":5}`, ``, true},
		{`{"name":"d","parameters":[1]}`, ``, true},
		{`"bare"`, ``, true},
	}
	for _, c := range cases {
		o, ok, err := toolsMCPJSON(miscJSON(t, c.tool), inst)
		if (err != nil) != c.malformed {
			t.Errorf("%s: err %v", c.tool, err)
			continue
		}
		got := ""
		if ok {
			b, _ := wirejson.Marshal(o, wirejson.Compact)
			got = string(b)
		}
		if got != c.want {
			t.Errorf("%s:\n got %s\nwant %s", c.tool, got, c.want)
		}
	}
}

func TestExportToolsReadsTheStoredColumn(t *testing.T) {
	got := exportTools([]byte(`{"tools":[{"type":"code","name":"agentarea/math"},{"type":"mcp","name":null},"junk",{"type":"mcp","name":7}]}`))
	want := []domain.ExportTool{{Type: "code", Name: "agentarea/math", HasName: true}, {Type: "mcp"}, {Type: "mcp", Name: "7", HasName: true}}
	if len(got) != len(want) {
		t.Fatalf("%+v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("[%d] = %+v, want %+v", i, got[i], want[i])
		}
	}
	if exportTools(nil) != nil || exportTools([]byte(`"x"`)) != nil {
		t.Error("no tools")
	}
}

func TestExportYAMLValueKeepsNumbers(t *testing.T) {
	v := exportYAMLValue(miscJSON(t, `{"a":[1,1.5,1e20,true,null,"s"]}`))
	if got := domain.SafeDumpYAML(v); got != "a:\n- 1\n- 1.5\n- 1.0e+20\n- true\n- null\n- s\n" {
		t.Errorf("%q", got)
	}
}
