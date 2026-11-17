package toolname

import (
	"strings"
	"testing"
)

func TestASCIISlug(t *testing.T) {
	for in, want := range map[string]string{
		"Привет, Мир!": "privet_mir",
		"Щука и ёж":    "schuka_i_ezh",
		"Café Déjà-vu": "cafe_deja_vu",
		"ﬁle  Ｎame":    "file_name",
		"Объект":       "obekt",
		"":             "",
	} {
		if got := ASCIISlug(in); got != want {
			t.Errorf("ASCIISlug(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestServerLabelAndQualify(t *testing.T) {
	if got := ServerLabel("  My Server.v2 "); got != "my_server_v2" {
		t.Fatalf("ascii label = %q", got)
	}
	if got := ServerLabel("Почта"); got != "pochta" {
		t.Fatalf("cyrillic label = %q", got)
	}
	if got := ServerLabel("中文"); got != "server" {
		t.Fatalf("empty label = %q", got)
	}
	if got := QualifyMCPToolName("GitHub", "create issue"); got != "mcp__github__create_issue" {
		t.Fatalf("qualified = %q", got)
	}
	long := QualifyMCPToolName("server", strings.Repeat("x", 80))
	if len(long) != MaxToolNameLength || long != QualifyMCPToolName("server", strings.Repeat("x", 80)) {
		t.Fatalf("long = %q (%d)", long, len(long))
	}
	if long == QualifyMCPToolName("server", strings.Repeat("x", 81)) {
		t.Fatalf("digest does not tell long names apart")
	}
}

func TestNarrowingNamesAndNamespace(t *testing.T) {
	got := MCPNarrowingNames("Git Hub", "push")
	want := []string{"mcp:Git Hub:push", "mcp__git_hub__push", "push"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("narrowing = %v", got)
	}
	prefix := "crm"
	for _, tc := range []struct {
		prefix   *string
		id, name string
		want     string
	}{
		{&prefix, "0123456789", "Anything", "crm"},
		{nil, "0123456789", "My-Server One", "my_server_one"},
		{nil, "0123456789", "Почта", "pochta"},
		{nil, "0123456789", "", "01234567"},
	} {
		if got := AggregateNamespace(tc.prefix, tc.id, tc.name); got != tc.want {
			t.Errorf("AggregateNamespace(%v, %q, %q) = %q, want %q", tc.prefix, tc.id, tc.name, got, tc.want)
		}
	}
}
