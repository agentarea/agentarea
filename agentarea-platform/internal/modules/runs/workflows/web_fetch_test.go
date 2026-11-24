package workflows

import (
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

func runFetches(t *testing.T, seenLinksOnly *bool, urls ...string) *fakeRun {
	t.Helper()
	f := newFakeRun()
	f.cfg.Tools = append(f.cfg.Tools, api.ToolDefinition{Name: "web_fetch_webpage", Parameters: map[string]any{"type": "object"}})
	f.cfg.Bindings["web_fetch_webpage"] = api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: "agentarea/web", Method: "fetch_webpage"}}
	var replies []LLMCallResult
	for i, u := range urls {
		replies = append(replies, calls(ToolCall{ID: "fetch-" + string(rune('a'+i)), Name: "web_fetch_webpage", Arguments: `{"url": "` + u + `"}`}))
	}
	f.llm[parentTask] = turns(append(replies, calls(complete("done", "done")))...)
	env := newEnv(t, f)
	req := request(nil)
	req.TaskQuery = "Summarise https://example.com/seen"
	if seenLinksOnly != nil {
		req.Policy.ContentSafety = &api.ContentSafetyPolicy{FetchSeenLinksOnly: seenLinksOnly}
	}
	env.ExecuteWorkflow(AgentExecutionWorkflow, req)
	if res := result(t, env); !res.Success {
		t.Fatalf("result = %+v", res)
	}
	return f
}

func deniedFetches(f *fakeRun) []string {
	var out []string
	for _, e := range f.eventData(parentTask, "tool.result") {
		if e["denied_by_policy"] == true {
			out = append(out, e["tool_call_id"].(string))
		}
	}
	return out
}

func TestAPublicURLIsFetchedByDefault(t *testing.T) {
	f := runFetches(t, nil, "https://agentarea.ai")
	if len(f.toolCalls) != 1 || f.toolCalls[0].Args["url"] != "https://agentarea.ai" {
		t.Fatalf("tool calls = %+v", f.toolCalls)
	}
	if denied := deniedFetches(f); len(denied) != 0 {
		t.Fatalf("denied = %v", denied)
	}
}

func TestSeenLinksOnlyDeniesAnUnseenURL(t *testing.T) {
	on := true
	f := runFetches(t, &on, "https://agentarea.ai", "https://example.com/seen")
	if len(f.toolCalls) != 1 || f.toolCalls[0].Args["url"] != "https://example.com/seen" {
		t.Fatalf("tool calls = %+v", f.toolCalls)
	}
	if denied := deniedFetches(f); len(denied) != 1 || denied[0] != "fetch-a" {
		t.Fatalf("denied = %v", denied)
	}
	tools := f.messages(parentTask, "tool")
	if len(tools) == 0 || !strings.Contains(tools[0].Content, "already appeared in this task") {
		t.Fatalf("tool rows = %+v", tools)
	}
}
