package transport

import (
	"context"
	"errors"
	"net/http"
	"reflect"
	"strconv"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

func openAIModel(t *testing.T, url string, p domain.Profile) Model {
	t.Helper()
	return Model{
		ProviderType: "openai",
		ModelName:    "m",
		APIKey:       "k",
		EndpointURL:  url,
		Prices:       Prices{Input: dec("0.001"), Output: dec("0.002")},
		Profile:      profile(t, p),
		Transport:    http.DefaultTransport,
	}
}

func TestOpenAIUsageOnlyFinalChunkIsNotDropped(t *testing.T) {
	srv, c := serveRaw(t, 200, openAISSE(
		`{"choices":[{"delta":{"content":"hello"}}]}`,
		`{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}`,
	))
	m := openAIModel(t, srv.URL, domain.Profile{})

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.deltas[0].Content != "hello" {
		t.Errorf("first delta = %+v", o.deltas[0])
	}
	last := o.deltas[len(o.deltas)-1]
	if last.Usage == nil || last.Usage.Total != 15 {
		t.Fatalf("last delta usage = %+v", last.Usage)
	}
	assertCost(t, "cost", last.Cost, "0.02")
	_, path, _, body := c.snapshot()
	if path != "/v1/chat/completions" {
		t.Errorf("path = %q", path)
	}
	assertJSON(t, "stream_options", body["stream_options"], `{"include_usage":true}`)
}

func TestOpenAIProviderWithoutEndpointIsCalledAtItsPublicAddress(t *testing.T) {
	srv, c := serveRaw(t, 200, openAISSE(
		`{"choices":[{"delta":{"content":"hello"}}]}`,
		`{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}`,
	))
	m := openAIModel(t, "", domain.Profile{BaseURL: srv.URL + "/api/v1/"})
	m.ProviderType = "openrouter"

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, path, header, _ := c.snapshot()
	if path != "/api/v1/chat/completions" {
		t.Errorf("path = %q", path)
	}
	if got := header.Get("Authorization"); got != "Bearer k" {
		t.Errorf("Authorization = %q", got)
	}
	if o.content != "hello" || o.usage == nil || o.usage.Total != 15 {
		t.Errorf("outcome = %+v", o)
	}
	assertCost(t, "cost", o.cost, "0.02")
}

func TestOpenAICompletionKeepsReasoningToolsAndAccounting(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(
		`{"choices":[{"delta":{"reasoning_content":"why"}}]}`,
		`{"choices":[{"delta":{"content":"hello"}}]}`,
		`{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"lookup","arguments":"{\"x\":"}}]}}]}`,
		`{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"1}"}}]}}]}`,
		`{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}`,
	))
	m := openAIModel(t, srv.URL, domain.Profile{})

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.reasoning != "why" || o.content != "hello" {
		t.Errorf("reasoning, content = %q, %q", o.reasoning, o.content)
	}
	want := []api.ToolCall{{ID: "call-1", Name: "lookup", Arguments: `{"x":1}`}}
	if !reflect.DeepEqual(o.toolCalls, want) {
		t.Errorf("tool calls = %+v", o.toolCalls)
	}
	if o.usage == nil || o.usage.Prompt != 10 || o.usage.Completion != 5 {
		t.Errorf("usage = %+v", o.usage)
	}
	assertCost(t, "cost", o.cost, "0.02")
}

func TestOpenAIReasoningFieldNamesAreReadInOrder(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(
		`{"choices":[{"delta":{"reasoning":"a"}}]}`,
		`{"choices":[{"delta":{"thinking":"b"}}]}`,
		`{"choices":[{"delta":{"reasoning_content":"c","reasoning":"x","thinking":"y"}}]}`,
		`{"choices":[{"delta":{"reasoning_content":"","reasoning":"d"}}]}`,
	))
	o, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.reasoning != "abcd" {
		t.Errorf("reasoning = %q", o.reasoning)
	}
}

func TestOpenAIToolCallSnapshotsAreCumulativeAndSortedByIndex(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(
		`{"choices":[{"delta":{"tool_calls":[{"index":1,"id":"b","function":{"name":"second","arguments":"{"}}]}}]}`,
		`{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a","function":{"name":"first","arguments":"{}"}}]}}]}`,
		`{"choices":[{"delta":{"tool_calls":[{"index":1,"function":{"arguments":"}"}}]}}]}`,
	))
	o, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if len(o.deltas) != 3 {
		t.Fatalf("deltas = %d", len(o.deltas))
	}
	wantFirst := []api.ToolCall{{ID: "b", Name: "second", Arguments: "{"}}
	if !reflect.DeepEqual(o.deltas[0].ToolCalls, wantFirst) {
		t.Errorf("first snapshot = %+v", o.deltas[0].ToolCalls)
	}
	want := []api.ToolCall{{ID: "a", Name: "first", Arguments: "{}"}, {ID: "b", Name: "second", Arguments: "{}"}}
	if !reflect.DeepEqual(o.deltas[2].ToolCalls, want) {
		t.Errorf("last snapshot = %+v", o.deltas[2].ToolCalls)
	}
}

func TestOpenAILegacyFunctionCallIsToolCallZero(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(
		`{"choices":[{"delta":{"function_call":{"name":"lookup","arguments":"{\"q\""}}}]}`,
		`{"choices":[{"delta":{"function_call":{"arguments":":1}"}}}]}`,
		`{"choices":[{"delta":{},"finish_reason":"function_call"}]}`,
	))
	o, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	want := []api.ToolCall{{Name: "lookup", Arguments: `{"q":1}`}}
	if !reflect.DeepEqual(o.toolCalls, want) || o.finish != "function_call" {
		t.Errorf("tool calls, finish = %+v, %q", o.toolCalls, o.finish)
	}
}

func TestOpenAIUsageOnTheLastContentChunkWithoutATotalIsAccounted(t *testing.T) {
	srv, _ := serveRaw(t, 200, "data:"+`{"choices":[{"delta":{"content":"hello"}}]}`+"\n"+openAISSE(
		`{"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":1000,"completion_tokens":100,"prompt_tokens_details":{"cached_tokens":800}}}`,
	))
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.Prices.CachedInput = dec("0.0001")

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.content != "hello" || o.finish != "stop" {
		t.Errorf("content, finish = %q, %q", o.content, o.finish)
	}
	if o.usage == nil || o.usage.Total != 1100 || o.usage.CachedPrompt != 800 {
		t.Fatalf("usage = %+v", o.usage)
	}
	assertCost(t, "cost", o.cost, "0.48")
	last := o.deltas[len(o.deltas)-1]
	if last.Usage == nil || last.FinishReason != "stop" {
		t.Errorf("usage rides on the finishing delta: %+v", last)
	}
}

func TestOpenAIReportedCostWinsOverConfiguredPrices(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(
		`{"choices":[{"delta":{"content":"hi"}}]}`,
		`{"choices":[],"usage":{"prompt_tokens":1000,"completion_tokens":100,"cost":0.00042}}`,
	))
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.Prices = Prices{Input: dec("1.5e-7"), Output: dec("6e-7")}

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	assertCost(t, "cost", o.cost, "0.00042")
}

func TestOpenAIConfiguredCostWithCacheReadAndWritePrices(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(
		`{"choices":[],"usage":{"prompt_tokens":1000,"completion_tokens":100,"prompt_tokens_details":{"cached_tokens":700,"cache_write_tokens":200}}}`,
	))
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.Prices.CachedInput = dec("0.0001")
	m.Prices.CacheCreation = dec("0.00125")

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.usage == nil || o.usage.CacheCreation != 200 {
		t.Fatalf("usage = %+v", o.usage)
	}
	assertCost(t, "cost", o.cost, "0.62")
}

func TestOpenAIUnpricedModelCostsZero(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(`{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}`))
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.Prices = Prices{Input: dec("0.001")}

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.usage == nil {
		t.Fatal("no usage")
	}
	assertCost(t, "cost", o.cost, "0")
}

func TestOpenAIDoneEndsTheStreamAndJunkLinesAreSkipped(t *testing.T) {
	body := ": keep-alive\n" +
		"event: chunk\n" +
		"id: 7\n" +
		"data: not json\n\n" +
		"data: {broken\n\n" +
		"data:\n\n" +
		"data: {} {}\n\n" +
		"data:{\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\r\n\r\n" +
		"data: {\"choices\":[{\"delta\":{\"content\":\"\"}}]}\n\n" +
		"data:  [DONE]  \n\n" +
		"data: {\"choices\":[{\"delta\":{\"content\":\"after\"}}]}\n\n"
	srv, _ := serveRaw(t, 200, body)

	o, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.content != "a" || len(o.deltas) != 1 {
		t.Errorf("content = %q over %d deltas", o.content, len(o.deltas))
	}
}

func TestOpenAIAChunkThatIsNotAnObjectFailsAsPythonDoes(t *testing.T) {
	cases := map[string]string{"[1]": "'list' object has no attribute 'get'", "3": "'int' object has no attribute 'get'",
		"1.5": "'float' object has no attribute 'get'", `"x"`: "'str' object has no attribute 'get'", "null": "'NoneType' object has no attribute 'get'"}
	for data, want := range cases {
		srv, _ := serveRaw(t, 200, openAISSE(data))
		_, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
		var pe *PyError
		if !errors.As(err, &pe) || pe.Type != "AttributeError" || pe.Msg != want {
			t.Errorf("%s: err = %v", data, err)
		}
	}
}

func TestOpenAIEndOfStreamWithoutDoneIsFine(t *testing.T) {
	srv, _ := serveRaw(t, 200, "data: {\"choices\":[{\"delta\":{\"content\":\"x\"}}]}")
	o, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	if err != nil || o.content != "x" {
		t.Errorf("content, err = %q, %v", o.content, err)
	}
}

func TestOpenAIBareCRLineEndingsSplitLines(t *testing.T) {
	srv, _ := serveRaw(t, 200, "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\r\rdata: {\"choices\":[{\"delta\":{\"content\":\"b\"}}]}\r\rdata: [DONE]\r\r")
	o, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.content != "ab" {
		t.Error("differs from Python: httpx aiter_lines splits on a bare \\r, Go only on \\n")
	}
}

func TestOpenAILineSeparatorInsideAChunkSplitsItAsHttpxDoes(t *testing.T) {
	srv, _ := serveRaw(t, 200, "data: {\"choices\":[{\"delta\":{\"content\":\"a b\"}}]}\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"c\"}}]}\n\n")
	o, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if o.content != "c" {
		t.Error("differs from Python: httpx splitlines() breaks a line at U+2028 and drops the chunk; Go keeps it")
	}
}

func TestOpenAIErrorInsideTheStreamIsAProviderError(t *testing.T) {
	cases := []struct {
		event   string
		status  int
		message string
	}{
		{`{"error":{"code":502,"message":"Upstream timed out"},"choices":[{"delta":{"content":""},"finish_reason":"error"}]}`, 502, "Upstream timed out"},
		{`{"error":{"code":429,"message":"Rate limited upstream"},"choices":[]}`, 429, "Rate limited upstream"},
		{`{"choices":[{"delta":{},"finish_reason":"error"}]}`, 502, "the provider ended the stream with an error"},
		{`{"error":{"code":"server_error","message":"Provider disconnected unexpectedly"},"choices":[{"delta":{"content":""},"finish_reason":"error"}]}`, 502, "server_error: Provider disconnected unexpectedly"},
		{`{"error":{"code":"invalid_api_key","message":"Key revoked"}}`, 401, "invalid_api_key: Key revoked"},
		{`{"error":{"code":"insufficient_quota","message":"Account not active"}}`, 402, "insufficient_quota: Account not active"},
		{`{"error":{"code":"rate_limit_exceeded","message":"Slow down"}}`, 429, "rate_limit_exceeded: Slow down"},
		{`{"error":{"code":"context_length_exceeded","message":"Too long"}}`, 400, "context_length_exceeded: Too long"},
		{`{"error":{"code":"content_filter","message":"Blocked"}}`, 400, "content_filter: Blocked"},
		{`{"error":{"code":"weird","message":"Odd"}}`, 502, "weird: Odd"},
		{`{"error":{"code":"","message":"Empty code"}}`, 502, "Empty code"},
		{`{"error":{"code":700,"message":"Out of range"}}`, 502, "Out of range"},
		{`{"error":{"code":399,"message":"Below range"}}`, 502, "Below range"},
		{`{"error":{"code":429.0,"message":"Float code"}}`, 502, "Float code"},
		{`{"error":{"code":true,"message":"Bool code"}}`, 502, "Bool code"},
		{`{"error":{"code":503}}`, 503, "the provider ended the stream with an error"},
		{`{"error":{"message":42}}`, 502, "42"},
		{`{"error":{"message":0.5}}`, 502, "0.5"},
		{`{"error":"upstream exploded"}`, 502, "upstream exploded"},
		{`{"error":1}`, 502, "the provider ended the stream with an error"},
	}
	for _, tc := range cases {
		srv, _ := serveRaw(t, 200, openAISSE(`{"choices":[{"delta":{"content":"par"}}]}`, tc.event))
		var seen []Delta
		err := openAIModel(t, srv.URL, domain.Profile{}).Stream(context.Background(), Request{Messages: userHi()}, func(d Delta) error {
			seen = append(seen, d)
			return nil
		})
		var he *ProviderHTTPError
		if !errors.As(err, &he) {
			t.Errorf("%s: err = %v", tc.event, err)
			continue
		}
		if he.StatusCode != tc.status || he.ProviderMessage != tc.message {
			t.Errorf("%s: got (%d, %q), want (%d, %q)", tc.event, he.StatusCode, he.ProviderMessage, tc.status, tc.message)
		}
		if want := "Provider returned HTTP " + strconv.Itoa(tc.status) + ": " + tc.message; he.Error() != want {
			t.Errorf("Error() = %q, want %q", he.Error(), want)
		}
		if len(seen) != 1 || seen[0].Content != "par" {
			t.Errorf("%s: deltas before the error = %+v", tc.event, seen)
		}
	}
}

func TestOpenAIStreamErrorWithAnObjectMessageReadsAsPythonStr(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(`{"error":{"code":"server_error","message":{"detail":"x"}}}`))
	_, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	var he *ProviderHTTPError
	if !errors.As(err, &he) {
		t.Fatalf("err = %v", err)
	}
	if he.ProviderMessage != "server_error: {'detail': 'x'}" {
		t.Errorf("differs from Python: str(dict) is %q in Python, Go writes %q", "{'detail': 'x'}", he.ProviderMessage)
	}
}

func TestOpenAIUsageOnAnErrorChunkIsNotAccountedBeforeTheError(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(`{"error":{"code":500,"message":"x"},"usage":{"prompt_tokens":1,"completion_tokens":1}}`))
	o, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	var he *ProviderHTTPError
	if !errors.As(err, &he) || he.StatusCode != 500 || len(o.deltas) != 0 {
		t.Errorf("err, deltas = %v, %d", err, len(o.deltas))
	}
}

func TestOpenAIErrorStatusBeforeTheStream(t *testing.T) {
	long := strings.Repeat("é", 600)
	cases := []struct {
		status int
		body   string
		want   string
	}{
		{429, `{"error":{"message":"slow down"}}`, "slow down"},
		{402, `{"error":{"message":"Insufficient credits","code":402}}`, "Insufficient credits"},
		{400, `{"type":"error","error":{"type":"invalid_request_error","message":"prompt is too long"}}`, "prompt is too long"},
		{400, `{"error":"bad request string"}`, "bad request string"},
		{400, `{"message":"top-level message"}`, "top-level message"},
		{400, `{"error":{"code":1}}`, `{"error":{"code":1}}`},
		{400, `{"error":{"message":5},"message":"fallback"}`, "fallback"},
		{400, `[1, 2]`, `[1, 2]`},
		{500, "  plain text failure \n", "plain text failure"},
		{503, "", ""},
		{500, long, strings.Repeat("é", 500)},
		{400, `{"error":{"message":"` + long + `"}}`, strings.Repeat("é", 500)},
	}
	for _, tc := range cases {
		srv, c := serveRaw(t, tc.status, tc.body)
		_, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
		var he *ProviderHTTPError
		if !errors.As(err, &he) {
			t.Errorf("%d %q: err = %v", tc.status, tc.body, err)
			continue
		}
		if he.StatusCode != tc.status || he.ProviderMessage != tc.want {
			t.Errorf("%d %.40q: got (%d, %.60q), want %.60q", tc.status, tc.body, he.StatusCode, he.ProviderMessage, tc.want)
		}
		if hits, _, _, _ := c.snapshot(); hits != 1 {
			t.Errorf("hits = %d", hits)
		}
	}
}

func TestOpenAIErrorBodyWithInvalidUTF8IsReplacedPerByte(t *testing.T) {
	srv, _ := serveRaw(t, 500, "bad \xff\xfe body")
	_, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi()})
	var he *ProviderHTTPError
	if !errors.As(err, &he) {
		t.Fatalf("err = %v", err)
	}
	if he.ProviderMessage != "bad �� body" {
		t.Errorf("differs from Python: decode(errors=\"replace\") gives one U+FFFD per bad byte, Go gives %q", he.ProviderMessage)
	}
}

func TestOpenAIRequestBody(t *testing.T) {
	srv, c := serveRaw(t, 200, openAISSE(`{"choices":[{"delta":{"content":"ok"}}]}`))
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.ModelName = "vendor/model"
	temp := 0.2
	r := Request{
		Messages: []api.Message{
			{Role: "system", Content: "be brief"},
			{Role: "user", Content: "<weather> & co"},
			{Role: "assistant", Content: "", ToolCalls: []api.ToolCall{{ID: "c1", Name: "weather", Arguments: `{"city":"Paris"}`}}},
			{Role: "tool", ToolCallID: "c1", Name: "weather", Content: "18C"},
		},
		Tools: []api.ToolDefinition{
			{Name: "weather", Description: "Current weather", Parameters: map[string]any{"type": "object", "properties": map[string]any{"city": map[string]any{"type": "string"}}}},
			{Name: "noargs"},
		},
		Temperature: &temp,
		MaxTokens:   100,
	}
	if _, err := runStream(context.Background(), m, r); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, _, header, body := c.snapshot()
	if got := header.Get("Content-Type"); got != "application/json" {
		t.Errorf("Content-Type = %q", got)
	}
	assertJSON(t, "body", body, `{
		"model": "vendor/model",
		"messages": [
			{"role": "system", "content": "be brief"},
			{"role": "user", "content": "<weather> & co"},
			{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "weather", "arguments": "{\"city\":\"Paris\"}"}}]},
			{"role": "tool", "tool_call_id": "c1", "name": "weather", "content": "18C"}
		],
		"stream": true,
		"stream_options": {"include_usage": true},
		"tools": [
			{"type": "function", "function": {"name": "weather", "description": "Current weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}},
			{"type": "function", "function": {"name": "noargs", "description": "", "parameters": {}}}
		],
		"tool_choice": "auto",
		"temperature": 0.2,
		"max_tokens": 100
	}`)
}

func TestOpenAIRequestBodyLeavesUnsetFieldsOut(t *testing.T) {
	srv, c := serveRaw(t, 200, openAISSE(`{"choices":[{"delta":{"content":"ok"}}]}`))
	zero := 0.0
	if _, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi(), Temperature: &zero}); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, _, _, body := c.snapshot()
	assertJSON(t, "body", body, `{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":true,"stream_options":{"include_usage":true},"temperature":0}`)
}

func TestOpenAIResponseSchemaIsAskedForAsResponseFormat(t *testing.T) {
	srv, c := serveRaw(t, 200, openAISSE(`{"choices":[{"delta":{"content":"{}"}}]}`))
	schema := map[string]any{"type": "object", "properties": map[string]any{"n": map[string]any{"type": "integer"}}}
	if _, err := runStream(context.Background(), openAIModel(t, srv.URL, domain.Profile{}), Request{Messages: userHi(), ResponseSchema: schema}); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, _, _, body := c.snapshot()
	assertJSON(t, "response_format", body["response_format"],
		`{"type":"json_schema","json_schema":{"name":"answer","schema":{"type":"object","properties":{"n":{"type":"integer"}}}}}`)
}

func TestOpenAIReasoningIsAskedForInTheProvidersForm(t *testing.T) {
	budget := 2048
	cases := []struct {
		param  string
		effort string
		budget *int
		want   string
	}{
		{domain.ReasoningEffortParam, "low", nil, `{"reasoning_effort":"low"}`},
		{domain.ReasoningObjectParam, "low", nil, `{"reasoning":{"effort":"low"}}`},
		{domain.ReasoningObjectParam, "", &budget, `{"reasoning":{"max_tokens":2048}}`},
	}
	for _, tc := range cases {
		srv, c := serveRaw(t, 200, openAISSE(`{"choices":[{"delta":{"content":"ok"}}]}`))
		m := openAIModel(t, srv.URL, domain.Profile{ReasoningParam: tc.param})
		if _, err := runStream(context.Background(), m, Request{Messages: userHi(), ReasoningEffort: tc.effort, ReasoningMaxTokens: tc.budget}); err != nil {
			t.Fatalf("%s: %v", tc.param, err)
		}
		_, _, _, body := c.snapshot()
		got := map[string]any{}
		for _, k := range []string{"reasoning", "reasoning_effort"} {
			if v, ok := body[k]; ok {
				got[k] = v
			}
		}
		assertJSON(t, tc.param, got, tc.want)
	}
}

func TestOpenAIReasoningSettingsItCannotTakeAreRefusedBeforeAnyIO(t *testing.T) {
	budget := 2048
	cases := []struct {
		param  string
		effort string
		budget *int
		says   string
	}{
		{domain.ReasoningEffortParam, "", &budget, "not a token budget"},
		{domain.ReasoningObjectParam, "low", &budget, "not both"},
		{domain.ReasoningEffortParam, "low", &budget, "not both"},
	}
	for _, tc := range cases {
		srv, c := serveRaw(t, 200, openAISSE())
		m := openAIModel(t, srv.URL, domain.Profile{ReasoningParam: tc.param})
		_, err := runStream(context.Background(), m, Request{Messages: userHi(), ReasoningEffort: tc.effort, ReasoningMaxTokens: tc.budget})
		var re *domain.ReasoningSettingError
		if !errors.As(err, &re) || !strings.Contains(re.Error(), tc.says) {
			t.Errorf("%s: err = %v", tc.param, err)
		}
		if PyType(err) != "ReasoningSettingError" {
			t.Errorf("PyType = %q", PyType(err))
		}
		if hits, _, _, _ := c.snapshot(); hits != 0 {
			t.Errorf("%s: the provider was called", tc.param)
		}
	}
}

func conversation() []api.Message {
	return []api.Message{
		{Role: "system", Content: "you are on call"},
		{Role: "user", Content: "check alerts"},
		{Role: "assistant", Content: "", ToolCalls: []api.ToolCall{{ID: "c1", Name: "m", Arguments: "{}"}}},
		{Role: "tool", ToolCallID: "c1", Content: "all green"},
	}
}

const conversationJSON = `[
	{"role": "system", "content": "you are on call"},
	{"role": "user", "content": "check alerts"},
	{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "m", "arguments": "{}"}}]},
	{"role": "tool", "tool_call_id": "c1", "content": "all green"}
]`

func sentMessages(t *testing.T, p domain.Profile, ms []api.Message) any {
	t.Helper()
	srv, c := serveRaw(t, 200, openAISSE(`{"choices":[{"delta":{"content":"ok"}}]}`))
	m := openAIModel(t, "", p)
	m.Profile.BaseURL = srv.URL + "/api/v1"
	if _, err := runStream(context.Background(), m, Request{Messages: ms}); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	_, _, _, body := c.snapshot()
	return body["messages"]
}

func TestOpenAICacheBreakpointsMarkTheSystemPromptAndTheLastTurn(t *testing.T) {
	sent := sentMessages(t, domain.Profile{CacheBreakpoints: true}, conversation())
	assertJSON(t, "messages", sent, `[
		{"role": "system", "content": [{"type": "text", "text": "you are on call", "cache_control": {"type": "ephemeral"}}]},
		{"role": "user", "content": "check alerts"},
		{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "m", "arguments": "{}"}}]},
		{"role": "tool", "tool_call_id": "c1", "content": [{"type": "text", "text": "all green", "cache_control": {"type": "ephemeral"}}]}
	]`)
}

func TestOpenAIBreakpointGoesOnTheLastPartOfAMultipartTurn(t *testing.T) {
	ms := []api.Message{
		{Role: "system", Content: ""},
		{Role: "user", Parts: []api.ContentPart{{Type: "text", Text: "what is this?"}, {Type: "image_url", ImageURL: "https://example.com/a.png"}}},
	}
	sent := sentMessages(t, domain.Profile{CacheBreakpoints: true}, ms)
	assertJSON(t, "messages", sent, `[
		{"role": "system", "content": ""},
		{"role": "user", "content": [
			{"type": "text", "text": "what is this?"},
			{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}, "cache_control": {"type": "ephemeral"}}
		]}
	]`)
}

func TestOpenAISendsAPDFAsAFilePart(t *testing.T) {
	ms := []api.Message{{Role: "user", Parts: []api.ContentPart{
		{Type: "text", Text: "Files returned by read_file (call c1):"},
		{Type: "file", FileData: "data:application/pdf;base64,JVBERi0=", Filename: "plan.pdf"},
	}}}
	assertJSON(t, "messages", sentMessages(t, domain.Profile{}, ms), `[{"role": "user", "content": [
		{"type": "text", "text": "Files returned by read_file (call c1):"},
		{"type": "file", "file": {"filename": "plan.pdf", "file_data": "data:application/pdf;base64,JVBERi0="}}
	]}]`)
}

func TestOpenAIOnlyTheLastSystemMessageAndAnEmptyLastTurnStaysUnmarked(t *testing.T) {
	ms := []api.Message{
		{Role: "system", Content: "first"},
		{Role: "user", Content: "q"},
		{Role: "system", Content: "second"},
		{Role: "assistant", Content: ""},
	}
	sent := sentMessages(t, domain.Profile{CacheBreakpoints: true}, ms)
	assertJSON(t, "messages", sent, `[
		{"role": "system", "content": "first"},
		{"role": "user", "content": "q"},
		{"role": "system", "content": [{"type": "text", "text": "second", "cache_control": {"type": "ephemeral"}}]},
		{"role": "assistant", "content": ""}
	]`)
}

func TestOpenAIProviderThatCachesOnItsOwnGetsTheMessagesUnmarked(t *testing.T) {
	sent := sentMessages(t, domain.Profile{}, conversation())
	assertJSON(t, "messages", sent, conversationJSON)
}

func TestAuthHeadersFollowTheAuthStyle(t *testing.T) {
	cases := []struct {
		auth, key string
		want      map[string]string
		absent    []string
	}{
		{domain.AuthBearer, "k", map[string]string{"Authorization": "Bearer k"}, []string{"X-Api-Key", "Anthropic-Version"}},
		{domain.AuthAPIKeyHeader, "k", map[string]string{"X-Api-Key": "k", "Anthropic-Version": "2023-06-01"}, []string{"Authorization"}},
		{domain.AuthNone, "k", nil, []string{"Authorization", "X-Api-Key", "Anthropic-Version"}},
		{domain.AuthBearer, "", nil, []string{"Authorization", "X-Api-Key", "Anthropic-Version"}},
		{domain.AuthAPIKeyHeader, "", nil, []string{"Authorization", "X-Api-Key", "Anthropic-Version"}},
	}
	for _, tc := range cases {
		srv, c := serveRaw(t, 200, openAISSE(`{"choices":[{"delta":{"content":"ok"}}]}`))
		m := openAIModel(t, srv.URL, domain.Profile{Auth: tc.auth})
		m.APIKey = tc.key
		if _, err := runStream(context.Background(), m, Request{Messages: userHi()}); err != nil {
			t.Fatalf("%s: %v", tc.auth, err)
		}
		_, _, header, _ := c.snapshot()
		for k, v := range tc.want {
			if got := header.Get(k); got != v {
				t.Errorf("%s/%q: %s = %q, want %q", tc.auth, tc.key, k, got, v)
			}
		}
		for _, k := range tc.absent {
			if _, ok := header[k]; ok {
				t.Errorf("%s/%q: %s sent", tc.auth, tc.key, k)
			}
		}
		if header.Get("Content-Type") != "application/json" {
			t.Errorf("Content-Type = %q", header.Get("Content-Type"))
		}
	}
}

func TestNoAddressIsRefused(t *testing.T) {
	for _, transport := range []string{domain.TransportOpenAI, domain.TransportAnthropic} {
		m := Model{ProviderType: "ollama", ModelName: "llama3", Profile: profile(t, domain.Profile{Transport: transport}), Transport: http.DefaultTransport}
		_, err := runStream(context.Background(), m, Request{Messages: userHi()})
		var na *NoAddressError
		if !errors.As(err, &na) {
			t.Fatalf("%s: err = %v", transport, err)
		}
		if err.Error() != "Provider 'ollama' has no public address and no endpoint_url is configured" {
			t.Errorf("message = %q", err.Error())
		}
		if PyType(err) != "ValueError" {
			t.Errorf("PyType = %q", PyType(err))
		}
		if _, ok := Classify(err); ok {
			t.Errorf("%s: a missing address is classified", transport)
		}
	}
}

func TestAnErrorFromYieldEndsTheCall(t *testing.T) {
	srv, _ := serveRaw(t, 200, openAISSE(
		`{"choices":[{"delta":{"content":"a"}}]}`,
		`{"choices":[{"delta":{"content":"b"}}]}`,
	))
	stop := errors.New("stop")
	calls := 0
	err := openAIModel(t, srv.URL, domain.Profile{}).Stream(context.Background(), Request{Messages: userHi()}, func(Delta) error {
		calls++
		return stop
	})
	if !errors.Is(err, stop) || calls != 1 {
		t.Errorf("err, calls = %v, %d", err, calls)
	}
}
