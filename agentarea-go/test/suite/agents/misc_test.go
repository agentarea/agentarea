//go:build suite

package agents

import (
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

// skipUnwired skips a test whose route answers 501: the port it needs from
// another module is not wired in this build yet. Any other status falls through.
func skipUnwired(t *testing.T, r *h.Response) *h.Response {
	t.Helper()
	if r.Status == http.StatusNotImplemented {
		t.Skipf("%s: port not wired yet", r.Body)
	}
	return r
}

func TestToolsAreNotAnAgentID(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Get(t, w.Path("/agents/tools?include=nothing")).Expect(http.StatusOK).Match([]any{})
	w.Owner.Get(t, w.Path("/agents/tools?mcp_instance_id=nope")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/agents/tools?include=mcp")).Expect(http.StatusOK).Match([]any{})
	w.Owner.Get(t, w.Path("/agents/tools?include=mcp&mcp_instance_id=00000000-0000-4000-8000-000000000000")).Expect(http.StatusOK).Match([]any{})
	w.Owner.Get(t, w.Path("/agents/tools")).Expect(http.StatusOK).Array()
	for _, tool := range w.Owner.Get(t, w.Path("/agents/tools?include=code")).Expect(http.StatusOK).Array() {
		o := tool.(map[string]any)
		if o["type"] != "code" || o["mcp_instance_id"] != nil || o["input_schema"] == nil {
			t.Errorf("code tool %v", o)
		}
	}
}

func TestPresetsAreNotAnAgentID(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Get(t, w.Path("/agents/presets")).Expect(http.StatusOK).Array()
}

func TestInstallUnknownAgent(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/agents/no-such-agent/install"), nil).Expect(http.StatusNotFound).Match(notFound())
}

func TestExportIsAnAdminYAMLAttachment(t *testing.T) {
	w := h.NewWorkspace(t)
	create(t, w.Owner, w, map[string]any{"name": "Exported Agent", "instruction": "Do it", "tools": []any{}})
	w.Member.Get(t, w.Path("/export")).Expect(http.StatusForbidden)
	resp := skipUnwired(t, w.Owner.Get(t, w.Path("/export"))).Expect(http.StatusOK)
	if ct := resp.ContentType(); ct != "text/plain" {
		t.Errorf("content-type %q", ct)
	}
	if cd := resp.Header.Get("Content-Disposition"); cd != "attachment; filename=workspace_config.yaml" {
		t.Errorf("content-disposition %q", cd)
	}
	body := string(resp.Body)
	if !strings.HasPrefix(body, "schema_version: 0.1.0\nname: "+w.Slug+"\n") ||
		!strings.Contains(body, "\n  name: Exported Agent\n  description: ''\n  instruction: Do it\n") {
		t.Errorf("export:\n%s", body)
	}
}

func TestExportCarriesSkillsAndMCPsWithoutSecrets(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/skills"), map[string]any{"content": "---\nname: Exported skill\ndescription: Does it\n---\n# Body\ntext"}).Expect(http.StatusOK)
	create(t, w.Owner, w, map[string]any{"name": "Skilled", "instruction": "Use it", "tools": []any{}})
	body := string(skipUnwired(t, w.Owner.Get(t, w.Path("/export"))).Expect(http.StatusOK).Body)
	for _, want := range []string{"\nmcps: []\n", "\nskills:\n- key: skill_exported_skill_", "  name: Exported skill\n  source_type: content\n", "\nagents:\n- key: ", "  name: Skilled\n"} {
		if !strings.Contains(body, want) {
			t.Errorf("export lacks %q:\n%s", want, body)
		}
	}
	if strings.Contains(body, "sk-") {
		t.Errorf("a credential is in the export:\n%s", body)
	}
}
