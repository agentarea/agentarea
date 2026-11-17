package transport

import (
	"context"
	"errors"
	"net/http"
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

func claude(t *testing.T, url string) Model {
	t.Helper()
	return Model{
		ProviderType: "anthropic",
		ModelName:    "claude-sonnet-4-5",
		APIKey:       "sk-ant",
		Prices:       Prices{Input: dec("0.000003"), Output: dec("0.000015"), CachedInput: dec("0.0000003")},
		Profile:      profile(t, domain.Profile{BaseURL: url + "/v1", Transport: domain.TransportAnthropic, Auth: domain.AuthAPIKeyHeader}),
		Transport:    http.DefaultTransport,
	}
}

var anthropicStream = []string{
	`{"type":"message_start","message":{"usage":{"input_tokens":100,"cache_read_input_tokens":900,"output_tokens":1}}}`,
	`{"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}`,
	`{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"hm"}}`,
	`{"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}`,
	`{"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Let me "}}`,
	`{"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"check."}}`,
	`{"type":"content_block_start","index":2,"content_block":{"type":"tool_use","id":"toolu_1","name":"weather","input":{}}}`,
	`{"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":"{\"city\": "}}`,
	`{"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":"\"Paris\"}"}}`,
	`{"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":50}}`,
	`{"type":"message_stop"}`,
}

func TestAnthropicStreamedAnswerKeepsTextThinkingToolsAndCost(t *testing.T) {
	srv, c := serveRaw(t, 200, anthropicSSE(t, anthropicStream...))
	r := Request{
		Messages: []api.Message{{Role: "system", Content: "be brief"}, {Role: "user", Content: "hi"}},
		Tools:    []api.ToolDefinition{{Name: "weather", Parameters: map[string]any{}}},
	}

	o, err := runStream(context.Background(), claude(t, srv.URL), r)
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, path, header, body := c.snapshot()
	if path != "/v1/messages" {
		t.Errorf("path = %q", path)
	}
	if header.Get("X-Api-Key") != "sk-ant" || header.Get("Anthropic-Version") != "2023-06-01" || header.Get("Authorization") != "" {
		t.Errorf("headers = %v", header)
	}
	if body["system"] != "be brief" || body["max_tokens"] != float64(4096) {
		t.Errorf("system, max_tokens = %v, %v", body["system"], body["max_tokens"])
	}
	assertJSON(t, "tool_choice", body["tool_choice"], `{"type":"auto"}`)
	if o.content != "Let me check." || o.reasoning != "hm" || o.finish != "tool_calls" {
		t.Errorf("content, reasoning, finish = %q, %q, %q", o.content, o.reasoning, o.finish)
	}
	want := []api.ToolCall{{ID: "toolu_1", Name: "weather", Arguments: `{"city": "Paris"}`}}
	if !reflect.DeepEqual(o.toolCalls, want) {
		t.Errorf("tool calls = %+v", o.toolCalls)
	}
	if o.usage == nil || o.usage.Prompt != 1000 || o.usage.CachedPrompt != 900 || o.usage.Completion != 50 || o.usage.Total != 1050 {
		t.Fatalf("usage = %+v", o.usage)
	}
	assertCost(t, "cost", o.cost, "0.00132")
}

func TestAnthropicDeltasArriveInStreamOrder(t *testing.T) {
	srv, _ := serveRaw(t, 200, anthropicSSE(t, anthropicStream...))
	o, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if len(o.deltas) != 7 {
		t.Fatalf("deltas = %+v", o.deltas)
	}
	if o.deltas[0].Reasoning != "hm" || o.deltas[1].Content != "Let me " || o.deltas[2].Content != "check." {
		t.Errorf("text deltas = %+v", o.deltas[:3])
	}
	args := []string{"", `{"city": `, `{"city": "Paris"}`}
	for i, a := range args {
		d := o.deltas[3+i]
		if len(d.ToolCalls) != 1 || d.ToolCalls[0].Arguments != a || d.Usage != nil || !d.Cost.IsZero() {
			t.Errorf("tool delta %d = %+v", i, d)
		}
	}
	last := o.deltas[6]
	if last.Usage == nil || last.FinishReason != "tool_calls" || last.Content != "" || last.ToolCalls != nil {
		t.Errorf("trailing delta = %+v", last)
	}
}

func TestAnthropicToolUseWithoutAnIndexTakesItsPosition(t *testing.T) {
	srv, _ := serveRaw(t, 200, anthropicSSE(t,
		`{"type":"content_block_start","content_block":{"type":"tool_use","id":"a","name":"one"}}`,
		`{"type":"content_block_start","content_block":{"type":"tool_use","id":"b","name":"two"}}`,
		`{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{}"}}`,
		`{"type":"content_block_delta","index":9,"delta":{"type":"input_json_delta","partial_json":"lost"}}`,
		`{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"lost"}}`,
		`{"type":"message_stop"}`,
	))
	o, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	want := []api.ToolCall{{ID: "a", Name: "one"}, {ID: "b", Name: "two", Arguments: "{}"}}
	if !reflect.DeepEqual(o.toolCalls, want) || len(o.deltas) != 3 {
		t.Errorf("tool calls = %+v over %d deltas", o.toolCalls, len(o.deltas))
	}
}

func TestAnthropicStopReasonInOpenAIWords(t *testing.T) {
	cases := map[string]string{"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls",
		"refusal": "content_filter", "pause_turn": "pause_turn"}
	for stop, want := range cases {
		srv, _ := serveRaw(t, 200, anthropicSSE(t,
			`{"type":"message_start","message":{"usage":{"input_tokens":5}}}`,
			`{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"pa"}}`,
			`{"type":"message_delta","delta":{"stop_reason":"`+stop+`"},"usage":{"output_tokens":9}}`,
			`{"type":"message_stop"}`,
		))
		o, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi()})
		if err != nil {
			t.Fatalf("%s: %v", stop, err)
		}
		if o.content != "pa" || o.finish != want {
			t.Errorf("%s: content, finish = %q, %q", stop, o.content, o.finish)
		}
	}
}

func TestAnthropicErrorEventStatus(t *testing.T) {
	cases := []struct {
		event   string
		status  int
		message string
	}{
		{`{"type":"error","error":{"type":"invalid_request_error","message":"m"}}`, 400, "m"},
		{`{"type":"error","error":{"type":"authentication_error","message":"m"}}`, 401, "m"},
		{`{"type":"error","error":{"type":"permission_error","message":"m"}}`, 403, "m"},
		{`{"type":"error","error":{"type":"not_found_error","message":"m"}}`, 404, "m"},
		{`{"type":"error","error":{"type":"request_too_large","message":"m"}}`, 413, "m"},
		{`{"type":"error","error":{"type":"rate_limit_error","message":"m"}}`, 429, "m"},
		{`{"type":"error","error":{"type":"api_error","message":"m"}}`, 500, "m"},
		{`{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}`, 529, "Overloaded"},
		{`{"type":"error","error":{"type":"something_new","message":"m"}}`, 500, "m"},
		{`{"type":"error","error":{"type":"overloaded_error"}}`, 529, "stream error"},
		{`{"type":"error"}`, 500, "stream error"},
		{`{"type":"error","error":{"type":"api_error","message":7}}`, 500, "7"},
	}
	for _, tc := range cases {
		srv, _ := serveRaw(t, 200, anthropicSSE(t, `{"type":"message_start","message":{"usage":{"input_tokens":1}}}`, tc.event))
		o, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi()})
		var he *ProviderHTTPError
		if !errors.As(err, &he) {
			t.Errorf("%s: err = %v", tc.event, err)
			continue
		}
		if he.StatusCode != tc.status || he.ProviderMessage != tc.message {
			t.Errorf("%s: got (%d, %q)", tc.event, he.StatusCode, he.ProviderMessage)
		}
		if len(o.deltas) != 0 {
			t.Errorf("%s: an error stream still yielded %+v", tc.event, o.deltas)
		}
	}
}

func TestAnthropicErrorEventWithANullMessageReadsAsPythonStr(t *testing.T) {
	srv, _ := serveRaw(t, 200, anthropicSSE(t, `{"type":"error","error":{"type":"api_error","message":null}}`))
	_, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi()})
	var he *ProviderHTTPError
	if !errors.As(err, &he) {
		t.Fatalf("err = %v", err)
	}
	if he.ProviderMessage != "None" {
		t.Errorf("differs from Python: str(None) is \"None\", Go writes %q", he.ProviderMessage)
	}
}

func TestAnthropicErrorStatusCarriesTheProviderMessage(t *testing.T) {
	srv, _ := serveRaw(t, 400, `{"type":"error","error":{"type":"invalid_request_error","message":"prompt is too long"}}`)
	_, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi()})
	var he *ProviderHTTPError
	if !errors.As(err, &he) || he.StatusCode != 400 || he.ProviderMessage != "prompt is too long" {
		t.Errorf("err = %v", err)
	}
}

func TestAnthropicTrailingDeltaCarriesUsageAndConfiguredCost(t *testing.T) {
	srv, _ := serveRaw(t, 200, anthropicSSE(t,
		`{"type":"message_start","message":{"usage":{"input_tokens":100,"cache_read_input_tokens":700,"cache_creation_input_tokens":200,"output_tokens":1}}}`,
		`{"type":"message_delta","delta":{},"usage":{"output_tokens":100,"cost":5}}`,
		`{"type":"message_stop"}`,
		`{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"after stop"}}`,
	))
	m := claude(t, srv.URL)
	m.Prices = Prices{Input: dec("0.001"), Output: dec("0.002"), CachedInput: dec("0.0001"), CacheCreation: dec("0.00125")}

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if len(o.deltas) != 1 || o.content != "" || o.finish != "" {
		t.Fatalf("deltas = %+v", o.deltas)
	}
	want := Usage{Prompt: 1000, Completion: 100, Total: 1100, CachedPrompt: 700, CacheCreation: 200}
	if o.usage == nil || *o.usage != want {
		t.Fatalf("usage = %+v", o.usage)
	}
	assertCost(t, "cost", o.cost, "0.62")
}

func TestAnthropicFinishWithoutUsageHasNoUsage(t *testing.T) {
	srv, _ := serveRaw(t, 200, anthropicSSE(t, `{"type":"message_delta","delta":{"stop_reason":"end_turn"}}`))
	o, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if len(o.deltas) != 1 || o.deltas[0].Usage != nil || o.finish != "stop" || !o.deltas[0].Cost.IsZero() {
		t.Errorf("deltas = %+v", o.deltas)
	}
}

func TestAnthropicNothingReportedYieldsNothing(t *testing.T) {
	srv, _ := serveRaw(t, 200, anthropicSSE(t, `{"type":"ping"}`, `{"type":"message_stop"}`)+"data: not json\n\n")
	o, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi()})
	if err != nil || len(o.deltas) != 0 {
		t.Errorf("deltas, err = %+v, %v", o.deltas, err)
	}
}

func TestAnthropicReasoningSettingsAreRefusedBeforeAnyIO(t *testing.T) {
	budget := 2048
	for _, r := range []Request{{Messages: userHi(), ReasoningEffort: "low"}, {Messages: userHi(), ReasoningMaxTokens: &budget}} {
		srv, c := serveRaw(t, 200, "")
		m := claude(t, srv.URL)
		_, err := runStream(context.Background(), m, r)
		var re *domain.ReasoningSettingError
		if !errors.As(err, &re) || re.Error() != "the Anthropic transport does not take reasoning settings yet" {
			t.Errorf("err = %v", err)
		}
		if hits, _, _, _ := c.snapshot(); hits != 0 {
			t.Error("the provider was called")
		}
		m.Profile.BaseURL = ""
		if _, err := runStream(context.Background(), m, r); !errors.As(err, &re) {
			t.Errorf("without an address: err = %v", err)
		}
	}
}

func TestAnthropicRequestBody(t *testing.T) {
	srv, c := serveRaw(t, 200, anthropicSSE(t, `{"type":"message_stop"}`))
	temp := 0.5
	r := Request{
		Messages: []api.Message{
			{Role: "system", Content: "be brief"},
			{Role: "system", Content: "use metric units"},
			{Role: "system", Content: ""},
			{Role: "user", Content: "weather in Paris?"},
			{Role: "assistant", Content: "", ToolCalls: []api.ToolCall{{ID: "toolu_1", Name: "weather", Arguments: `{"city": "Paris"}`}}},
			{Role: "tool", ToolCallID: "toolu_1", Content: "18C"},
			{Role: "user", Content: "and tomorrow?"},
			{Role: "user", Parts: []api.ContentPart{
				{Type: "text", Text: "what is this?"},
				{Type: "text", Text: ""},
				{Type: "image_url", ImageURL: "data:image/png;base64,iVBOR"},
				{Type: "image_url", ImageURL: "https://example.com/a.jpg"},
			}},
			{Role: "assistant", Content: "sure", ToolCalls: []api.ToolCall{{ID: "toolu_2", Name: "noargs"}, {ID: "toolu_3", Name: "bad", Arguments: "not json"}, {ID: "toolu_4", Name: "list", Arguments: "[1]"}}},
			{Role: "assistant", Content: "more"},
			{Role: "user", Content: ""},
		},
		Tools: []api.ToolDefinition{
			{Name: "weather", Description: "Current weather", Parameters: map[string]any{"type": "object", "properties": map[string]any{"city": map[string]any{"type": "string"}}}},
			{Name: "noargs", Parameters: map[string]any{}},
		},
		Temperature: &temp,
	}
	if _, err := runStream(context.Background(), claude(t, srv.URL), r); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, _, _, body := c.snapshot()
	assertJSON(t, "body", body, `{
		"model": "claude-sonnet-4-5",
		"system": "be brief\n\nuse metric units",
		"messages": [
			{"role": "user", "content": [{"type": "text", "text": "weather in Paris?"}]},
			{"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "weather", "input": {"city": "Paris"}}]},
			{"role": "user", "content": [
				{"type": "tool_result", "tool_use_id": "toolu_1", "content": "18C"},
				{"type": "text", "text": "and tomorrow?"},
				{"type": "text", "text": "what is this?"},
				{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR"}},
				{"type": "image", "source": {"type": "url", "url": "https://example.com/a.jpg"}}
			]},
			{"role": "assistant", "content": [
				{"type": "text", "text": "sure"},
				{"type": "tool_use", "id": "toolu_2", "name": "noargs", "input": {}},
				{"type": "tool_use", "id": "toolu_3", "name": "bad", "input": {}},
				{"type": "tool_use", "id": "toolu_4", "name": "list", "input": {}},
				{"type": "text", "text": "more"}
			]}
		],
		"max_tokens": 4096,
		"stream": true,
		"cache_control": {"type": "ephemeral"},
		"tools": [
			{"name": "weather", "description": "Current weather", "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}},
			{"name": "noargs", "description": "", "input_schema": {"type": "object", "properties": {}}}
		],
		"tool_choice": {"type": "auto"},
		"temperature": 0.5
	}`)
}

func TestAnthropicRequestBodyWithoutSystemOrTools(t *testing.T) {
	srv, c := serveRaw(t, 200, anthropicSSE(t, `{"type":"message_stop"}`))
	if _, err := runStream(context.Background(), claude(t, srv.URL), Request{Messages: userHi(), MaxTokens: 1000}); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, _, _, body := c.snapshot()
	assertJSON(t, "body", body, `{"model":"claude-sonnet-4-5","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],"max_tokens":1000,"stream":true,"cache_control":{"type":"ephemeral"}}`)
}

func TestAnthropicToolResultWithPartsIsJSONDumped(t *testing.T) {
	system, turns := anthropicMessages(openAIMessages([]api.Message{
		{Role: "tool", ToolCallID: "t1", Parts: []api.ContentPart{{Type: "text", Text: "ok"}}},
	}), func(string) {})
	if system != "" || len(turns) != 1 {
		t.Fatalf("system, turns = %q, %+v", system, turns)
	}
	block := turns[0].(map[string]any)["content"].([]any)[0].(map[string]any)
	if got := block["content"]; got != `[{"type": "text", "text": "ok"}]` {
		t.Errorf("differs from Python: json.dumps keeps the dict's key order, Go writes %q", got)
	}
}
