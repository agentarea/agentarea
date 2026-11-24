package domain

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

func kinds(leaks []Leak) []string {
	var out []string
	for _, l := range leaks {
		out = append(out, l.Kind+":"+l.Sample)
	}
	return out
}

func TestFindLeaks(t *testing.T) {
	cases := []struct {
		name, text, lang string
		tools            []string
		want             []string
	}{
		{"clean", "The report is ready.", "", nil, nil},
		{"cjk in russian", "Отчёт готов 你好 мир", "ru", nil, []string{"cjk:你好"}},
		{"cjk allowed in chinese", "报告已准备好", "zh", nil, nil},
		{"tool name hides identifier", "I called web_search for you", "", []string{"web_search"}, []string{"tool_name:web_search"}},
		{"identifier", "status is task_not_found now", "", nil, []string{"identifier:task_not_found"}},
		{"identifier inside a cyrillic word is no word", "жtask_not_found", "", nil, nil},
		{"stack trace", "it failed: Traceback (most recent call last) here", "", nil, []string{"stack_trace:Traceback (most recent call last)"}},
		{"type error word", "got a TypeError back", "", nil, []string{"stack_trace:TypeError"}},
		{"json", `see {"status": 1}`, "", nil, []string{`json:{"status":`}},
		{"english in russian", "Отчёт готов, файл в папке, всё сделано, report внутри", "ru", nil, []string{"english:report"}},
		{"allowed word and link skipped", "Отчёт готов, смотрите https внутри и https://x.io/file_name_here", "ru", nil, nil},
		{"file names are data", "Файл my_report_final.xlsx готов", "ru", nil, nil},
		{"code fences are data", "Готово ```some_code_name``` всё", "", nil, nil},
	}
	for _, c := range cases {
		got := kinds(FindLeaks(c.text, c.tools, c.lang))
		if len(got) != len(c.want) {
			t.Errorf("%s: got %v, want %v", c.name, got, c.want)
			continue
		}
		for i := range got {
			if got[i] != c.want[i] {
				t.Errorf("%s: got %v, want %v", c.name, got, c.want)
			}
		}
	}
}

func TestAnswerCheckConfigRuleWins(t *testing.T) {
	on := &api.AnswerCheck{Enabled: true, Language: "ru"}
	off := &api.AnswerCheck{Enabled: false}
	if AnswerCheckConfig(api.Policy{}, on) != on {
		t.Fatal("agent setting not used")
	}
	ruled := api.Policy{ContentSafety: &api.ContentSafetyPolicy{AnswerCheck: off}}
	if AnswerCheckConfig(ruled, on) != nil {
		t.Fatal("a rule turning the check off must win")
	}
	ruled.ContentSafety.AnswerCheck = on
	if AnswerCheckConfig(ruled, off) != on {
		t.Fatal("a rule turning the check on must win")
	}
}

func TestAcceptRewrite(t *testing.T) {
	orig := "See https://a.io/x and 你好"
	if r := AcceptRewrite(orig, "<changes>a</changes><answer> See https://a.io/x 你好 now </answer>", true); r == nil || r.Answer != "See https://a.io/x now" || r.Changes != "a" {
		t.Fatalf("rewrite = %+v", r)
	}
	for _, bad := range []string{"no block", "<answer></answer>", "<answer>a</answer><answer>b</answer>", "<answer>dropped the link</answer>"} {
		if AcceptRewrite(orig, bad, false) != nil {
			t.Errorf("%q accepted", bad)
		}
	}
	if names := ToolNamesOf([]api.ToolDefinition{{Name: "mcp__srv__fetch"}, {Name: "fetch"}}); len(names) != 3 || names[1] != "fetch" {
		t.Fatalf("names = %v", names)
	}
}
