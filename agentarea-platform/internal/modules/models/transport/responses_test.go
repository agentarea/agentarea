package transport

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

func responsesSSE(events ...string) string {
	var b strings.Builder
	for _, e := range events {
		b.WriteString("data: " + e + "\n\n")
	}
	return b.String()
}

func chatGPTModel(t *testing.T, base string) Model {
	t.Helper()
	m := openAIModel(t, "", domain.Profile{BaseURL: base + "/backend-api/codex", Transport: domain.TransportResponses, Auth: domain.AuthChatGPT})
	m.ModelName, m.APIKey, m.AccountID = "gpt-x", "access-1", "acc-1"
	return m
}

func TestResponsesRequestCarriesTheConversationAndTheChatGPTAccount(t *testing.T) {
	srv, c := serveRaw(t, 200, responsesSSE(`{"type":"response.completed","response":{"usage":{"input_tokens":3,"output_tokens":1}}}`))
	temp := 0.2
	_, err := runStream(context.Background(), chatGPTModel(t, srv.URL), Request{
		Messages: []api.Message{
			{Role: "system", Content: "be brief"},
			{Role: "user", Content: "list files"},
			{Role: "assistant", Content: "sure", ToolCalls: []api.ToolCall{{ID: "call_1", Name: "ls", Arguments: `{"dir":"."}`}}},
			{Role: "tool", ToolCallID: "call_1", Content: "a.txt"},
		},
		Tools:       []api.ToolDefinition{{Name: "ls", Description: "list", Parameters: map[string]any{"type": "object"}}},
		Temperature: &temp, MaxTokens: 100, ReasoningEffort: "high",
	})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, path, header, body := c.snapshot()
	if path != "/backend-api/codex/responses" {
		t.Errorf("path = %q", path)
	}
	for k, want := range map[string]string{"Authorization": "Bearer access-1", "Chatgpt-Account-Id": "acc-1", "Originator": "agentarea"} {
		if got := header.Get(k); got != want {
			t.Errorf("header %s = %q, want %q", k, got, want)
		}
	}
	assertJSON(t, "body", body, `{
		"model":"gpt-x","store":false,"stream":true,"tool_choice":"auto","parallel_tool_calls":false,
		"reasoning":{"effort":"high","summary":"auto"},
		"tools":[{"type":"function","name":"ls","description":"list","parameters":{"type":"object"},"strict":false}],
		"input":[
			{"type":"message","role":"developer","content":[{"type":"input_text","text":"be brief"}]},
			{"type":"message","role":"user","content":[{"type":"input_text","text":"list files"}]},
			{"type":"message","role":"assistant","content":[{"type":"output_text","text":"sure"}]},
			{"type":"function_call","call_id":"call_1","name":"ls","arguments":"{\"dir\":\".\"}"},
			{"type":"function_call_output","call_id":"call_1","output":"a.txt"}
		]}`)
}

func TestResponsesStreamFoldsTextReasoningToolCallsAndUsage(t *testing.T) {
	srv, _ := serveRaw(t, 200, responsesSSE(
		`{"type":"response.created","response":{}}`,
		`{"type":"response.reasoning_summary_text.delta","delta":"thinking"}`,
		`{"type":"response.output_text.delta","delta":"hel"}`,
		`{"type":"response.output_text.delta","delta":"lo"}`,
		`{"type":"response.output_item.added","item":{"type":"function_call","id":"fc_1","call_id":"call_9","name":"ls","arguments":""}}`,
		`{"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":"{}"}`,
		`{"type":"response.output_item.done","item":{"type":"function_call","id":"fc_1","call_id":"call_9","name":"ls","arguments":"{}"}}`,
		`{"type":"response.completed","response":{"usage":{"input_tokens":10,"input_tokens_details":{"cached_tokens":4},"output_tokens":5,"total_tokens":15}}}`,
	))
	o, err := runStream(context.Background(), chatGPTModel(t, srv.URL), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.content != "hello" || o.reasoning != "thinking" || o.finish != "tool_calls" {
		t.Errorf("content=%q reasoning=%q finish=%q", o.content, o.reasoning, o.finish)
	}
	if len(o.toolCalls) != 1 || o.toolCalls[0] != (api.ToolCall{ID: "call_9", Name: "ls", Arguments: "{}"}) {
		t.Errorf("tool calls = %+v", o.toolCalls)
	}
	if o.usage == nil || *o.usage != (Usage{Prompt: 10, Completion: 5, Total: 15, CachedPrompt: 4}) {
		t.Errorf("usage = %+v", o.usage)
	}
}

func TestResponsesFailedEventIsAProviderError(t *testing.T) {
	srv, _ := serveRaw(t, 200, responsesSSE(
		`{"type":"response.failed","response":{"error":{"code":"rate_limit_exceeded","message":"slow down"}}}`,
	))
	_, err := runStream(context.Background(), chatGPTModel(t, srv.URL), Request{Messages: userHi()})
	var h *ProviderHTTPError
	if !errors.As(err, &h) || h.StatusCode != 429 || h.ProviderMessage != "rate_limit_exceeded: slow down" {
		t.Fatalf("err = %v", err)
	}
}

func TestResponsesWithAnAPIKeySendsTheLimits(t *testing.T) {
	srv, c := serveRaw(t, 200, responsesSSE(`{"type":"response.completed","response":{}}`))
	m := openAIModel(t, srv.URL, domain.Profile{Transport: domain.TransportResponses})
	temp := 0.5
	if _, err := runStream(context.Background(), m, Request{Messages: userHi(), Temperature: &temp, MaxTokens: 7}); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, path, header, body := c.snapshot()
	if path != "/v1/responses" || header.Get("Chatgpt-Account-Id") != "" {
		t.Errorf("path = %q, account header = %q", path, header.Get("Chatgpt-Account-Id"))
	}
	if body["temperature"] != 0.5 || body["max_output_tokens"] != float64(7) || body["tools"] != nil {
		t.Errorf("body = %v", body)
	}
}

func liteModel(t *testing.T, base string) Model {
	t.Helper()
	m := chatGPTModel(t, base)
	m.ModelName, m.ResponsesLite = "gpt-6.2-sol", true
	return m
}

var lsTool = []api.ToolDefinition{{Name: "ls", Description: "list", Parameters: map[string]any{"type": "object"}}}

func TestAResponsesLiteRequestSendsItsToolsAsOneAdditionalToolsItem(t *testing.T) {
	srv, c := serveRaw(t, 200, responsesSSE(`{"type":"response.completed","response":{}}`))
	_, err := runStream(context.Background(), liteModel(t, srv.URL), Request{
		Messages: []api.Message{{Role: "system", Content: "be brief"}, {Role: "user", Content: "list files"}},
		Tools:    lsTool, ReasoningEffort: "high",
	})
	if err != nil {
		t.Fatal(err)
	}
	_, _, header, body := c.snapshot()
	if header.Get("X-Openai-Internal-Codex-Responses-Lite") != "true" {
		t.Errorf("lite header = %q", header.Get("X-Openai-Internal-Codex-Responses-Lite"))
	}
	assertJSON(t, "body", body, `{
		"model":"gpt-6.2-sol","store":false,"stream":true,"tool_choice":"auto","parallel_tool_calls":false,
		"reasoning":{"effort":"high","summary":"auto","context":"all_turns"},
		"input":[
			{"type":"additional_tools","role":"developer","tools":[{"type":"namespace","name":"functions","description":"",
				"tools":[{"type":"function","name":"ls","description":"list","parameters":{"type":"object"},"strict":false}]}]},
			{"type":"message","role":"developer","content":[{"type":"input_text","text":"be brief"}]},
			{"type":"message","role":"user","content":[{"type":"input_text","text":"list files"}]}
		]}`)
}

func TestANonLiteRequestKeepsTopLevelToolsAndNoLiteHeader(t *testing.T) {
	srv, c := serveRaw(t, 200, responsesSSE(`{"type":"response.completed","response":{}}`))
	if _, err := runStream(context.Background(), chatGPTModel(t, srv.URL), Request{Messages: userHi(), Tools: lsTool}); err != nil {
		t.Fatal(err)
	}
	_, _, header, body := c.snapshot()
	if header.Get("X-Openai-Internal-Codex-Responses-Lite") != "" || body["reasoning"] != nil {
		t.Errorf("lite header = %q, reasoning = %v", header.Get("X-Openai-Internal-Codex-Responses-Lite"), body["reasoning"])
	}
	assertJSON(t, "tools", body["tools"], `[{"type":"function","name":"ls","description":"list","parameters":{"type":"object"},"strict":false}]`)
	if input, _ := body["input"].([]any); len(input) != 1 {
		t.Errorf("input = %v", body["input"])
	}
}

func TestAResponsesLiteToolCallRoundTrips(t *testing.T) {
	srv, _ := serveRaw(t, 200, responsesSSE(
		`{"type":"response.output_item.added","item":{"type":"function_call","id":"fc_1","namespace":"functions","call_id":"call_7","name":"ls","arguments":""}}`,
		`{"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":"{\"dir\":\".\"}"}`,
		`{"type":"response.output_item.done","item":{"type":"function_call","id":"fc_1","namespace":"functions","call_id":"call_7","name":"ls","arguments":"{\"dir\":\".\"}"}}`,
		`{"type":"response.completed","response":{"usage":{"input_tokens":3,"output_tokens":2}}}`,
	))
	m := liteModel(t, srv.URL)
	o, err := runStream(context.Background(), m, Request{Messages: userHi(), Tools: lsTool})
	if err != nil {
		t.Fatal(err)
	}
	want := api.ToolCall{ID: "call_7", Name: "ls", Arguments: `{"dir":"."}`}
	if len(o.toolCalls) != 1 || o.toolCalls[0] != want || o.finish != "tool_calls" {
		t.Fatalf("tool calls = %+v finish = %q", o.toolCalls, o.finish)
	}

	next, c := serveRaw(t, 200, responsesSSE(`{"type":"response.completed","response":{}}`))
	m = liteModel(t, next.URL)
	history := append(userHi(),
		api.Message{Role: "assistant", ToolCalls: o.toolCalls},
		api.Message{Role: "tool", ToolCallID: "call_7", Content: "a.txt"})
	if _, err := runStream(context.Background(), m, Request{Messages: history, Tools: lsTool}); err != nil {
		t.Fatal(err)
	}
	_, _, _, body := c.snapshot()
	input, _ := body["input"].([]any)
	if len(input) != 4 {
		t.Fatalf("input = %v", body["input"])
	}
	assertJSON(t, "replayed call", input[2], `{"type":"function_call","namespace":"functions","call_id":"call_7","name":"ls","arguments":"{\"dir\":\".\"}"}`)
	assertJSON(t, "tool result", input[3], `{"type":"function_call_output","call_id":"call_7","output":"a.txt"}`)
}
