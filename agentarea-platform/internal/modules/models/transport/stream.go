// Package transport is the LLM wire: one chat call over the transport the
// provider's profile names (llm_model.py), streamed as deltas.
package transport

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptrace"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

// ReadTimeout is httpx.Timeout(300): the longest wait for any read.
const ReadTimeout = 300 * time.Second

const anthropicDefaultMaxTokens = 4096

const errorBodyLimit = 1 << 20

// CallDeadline bounds a whole call, however steadily bytes arrive.
const CallDeadline = 10 * time.Minute

// StreamBodyLimit bounds the bytes one answer may stream.
const StreamBodyLimit int64 = 64 << 20

// LineLimit bounds one line of an answer's stream.
const LineLimit = 4 << 20

var errIdle = errors.New("timed out")

type deadlineError struct{ d time.Duration }

func (e deadlineError) Error() string {
	return fmt.Sprintf("timed out: the call ran past its %v deadline", e.d)
}
func (e deadlineError) Is(target error) bool { return target == errIdle }

func tooLarge(what string, limit int64) error {
	return &PyError{Type: "ResponseTooLarge", Msg: fmt.Sprintf("Provider response exceeded the %d-byte limit of %s", limit, what)}
}

func anthropicStreamErrorStatus() map[string]int {
	return map[string]int{
		"invalid_request_error": 400, "authentication_error": 401, "permission_error": 403, "not_found_error": 404,
		"request_too_large": 413, "rate_limit_error": 429, "api_error": 500, "overloaded_error": 529,
	}
}

func streamErrorCodeStatus() map[string]int {
	return map[string]int{
		"invalid_api_key": 401, "insufficient_quota": 402, "rate_limit_exceeded": 429,
		"context_length_exceeded": 400, "content_filter": 400, "server_error": 502,
	}
}

func anthropicFinishReason() map[string]string {
	return map[string]string{
		"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls", "refusal": "content_filter",
	}
}

// NoRedirects is httpx's default: a redirect is the answer, not followed.
func NoRedirects(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }

// Model is one model at one provider (LLMModel).
type Model struct {
	ProviderType string
	ModelName    string
	APIKey       string
	EndpointURL  string
	Prices       Prices
	Profile      domain.Profile
	// Transport carries the call: member-vetted for a member's endpoint, plain otherwise.
	Transport http.RoundTripper
	// Timeout bounds every wait; zero is ReadTimeout.
	Timeout time.Duration
	// Deadline bounds the whole call; zero is CallDeadline.
	Deadline time.Duration
	// BodyLimit bounds the streamed answer; zero is StreamBodyLimit.
	BodyLimit int64
	// AccountID is the ChatGPT account a ChatGPT sign-in calls as.
	AccountID string
	// ResponsesLite sends the tools as one additional_tools item (codex-rs use_responses_lite).
	ResponsesLite bool
}

// Request is LLMRequest.
type Request struct {
	Messages           []api.Message
	Tools              []api.ToolDefinition
	Temperature        *float64
	MaxTokens          int
	ReasoningEffort    string
	ReasoningMaxTokens *int
}

// Delta is one LLMResponse of the stream: only what is new, tool calls as a
// cumulative snapshot, usage and cost on the deltas that report them.
type Delta struct {
	Content, Reasoning string
	ToolCalls          []api.ToolCall
	Usage              *Usage
	Cost               money.Decimal
	FinishReason       string
}

func (m Model) apiURL(path string) (string, error) {
	u := m.Profile.APIURL(m.EndpointURL, path)
	if u == "" {
		return "", &NoAddressError{ProviderType: m.ProviderType}
	}
	return u, nil
}

func (m Model) configuredCost(u Usage) money.Decimal { return ConfiguredCost(m.Prices, u) }

// Stream calls the model and hands each delta to yield; an error from yield ends the call.
func (m Model) Stream(ctx context.Context, r Request, yield func(Delta) error) error {
	var err error
	switch m.Profile.Transport {
	case domain.TransportAnthropic:
		err = m.streamAnthropic(ctx, r, yield)
	case domain.TransportResponses:
		err = m.streamResponses(ctx, r, yield)
	default:
		err = m.streamOpenAI(ctx, r, yield)
	}
	if err != nil && !errors.Is(err, context.Canceled) {
		slog.ErrorContext(ctx, "LLM call failed", "provider_type", m.ProviderType, "model_name", m.ModelName,
			"has_api_key", m.APIKey != "", "endpoint_url", m.EndpointURL, "error_type", PyType(err), "error_message", err.Error(), "streaming", true)
	}
	return err
}

// idleBody ends the request when no byte arrives for the timeout.
type idleBody struct {
	ctx      context.Context
	r        io.ReadCloser
	timer    *time.Timer
	deadline *time.Timer
	d        time.Duration
	cancel   context.CancelCauseFunc
	read     int64
	limit    int64
}

func (b *idleBody) Read(p []byte) (int, error) {
	if b.read >= b.limit {
		return 0, tooLarge("the answer", b.limit)
	}
	if rest := b.limit - b.read; int64(len(p)) > rest {
		p = p[:rest]
	}
	n, err := b.r.Read(p)
	b.read += int64(n)
	if n > 0 {
		b.timer.Reset(b.d)
	}
	return n, err
}

func (b *idleBody) Close() error {
	b.timer.Stop()
	b.deadline.Stop()
	b.cancel(nil)
	return b.r.Close()
}

func (m Model) send(ctx context.Context, url string, payload any) (*idleBody, int, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(payload); err != nil {
		return nil, 0, err
	}
	timeout := m.Timeout
	if timeout == 0 {
		timeout = ReadTimeout
	}
	deadline := m.Deadline
	if deadline == 0 {
		deadline = CallDeadline
	}
	limit := m.BodyLimit
	if limit == 0 {
		limit = StreamBodyLimit
	}
	cctx, cancel := context.WithCancelCause(ctx)
	timer := time.AfterFunc(timeout, func() { cancel(errIdle) })
	overall := time.AfterFunc(deadline, func() { cancel(deadlineError{deadline}) })
	req, err := http.NewRequestWithContext(cctx, http.MethodPost, url, bytes.NewReader(bytes.TrimRight(buf.Bytes(), "\n")))
	if err != nil {
		timer.Stop()
		overall.Stop()
		cancel(nil)
		err = netguard.SafeURLError(err)
		return nil, 0, &PyError{Type: "UnsupportedProtocol", Msg: err.Error(), Cause: err}
	}
	req.Header.Set("Content-Type", "application/json")
	for k, v := range m.Profile.Headers(m.APIKey) {
		req.Header.Set(k, v)
	}
	if m.Profile.Auth == domain.AuthChatGPT {
		for k, v := range chatGPTHeaders(m.AccountID) {
			req.Header.Set(k, v)
		}
	}
	if m.ResponsesLite {
		req.Header.Set("x-openai-internal-codex-responses-lite", "true")
	}
	var connected, wrote atomic.Bool
	req = req.WithContext(httptrace.WithClientTrace(req.Context(), &httptrace.ClientTrace{
		GotConn:      func(httptrace.GotConnInfo) { connected.Store(true) },
		WroteRequest: func(httptrace.WroteRequestInfo) { wrote.Store(true) },
	}))
	client := &http.Client{Transport: m.Transport, CheckRedirect: NoRedirects}
	resp, err := client.Do(req)
	if err != nil {
		err = netguard.SafeURLError(err)
		timer.Stop()
		overall.Stop()
		cause := context.Cause(cctx)
		cancel(nil)
		if errors.Is(cause, errIdle) {
			err = fmt.Errorf("%w: %w", cause, err)
		}
		if ctx.Err() != nil {
			return nil, 0, ctx.Err()
		}
		phase := "connect"
		switch {
		case wrote.Load():
			phase = "read"
		case connected.Load():
			phase = "write"
		}
		return nil, 0, classifyTransport(err, phase)
	}
	timer.Reset(timeout)
	body := &idleBody{ctx: cctx, r: resp.Body, timer: timer, deadline: overall, d: timeout, cancel: cancel, limit: limit}
	if resp.StatusCode >= 400 {
		raw, _ := io.ReadAll(io.LimitReader(body, errorBodyLimit))
		_ = body.Close()
		return nil, 0, &ProviderHTTPError{StatusCode: resp.StatusCode, ProviderMessage: errorBodyMessage(raw)}
	}
	return body, resp.StatusCode, nil
}

// lineBreak is a character str.splitlines (httpx's LineDecoder) ends a line at.
func lineBreak(r rune) bool {
	switch r {
	case '\n', '\r', '\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\u0085', '\u2028', '\u2029':
		return true
	}
	return false
}

// lines yields each line of an SSE body that starts with "data:", its payload
// trimmed. Lines end where aiter_lines ends them.
func lines(ctx context.Context, body *idleBody, each func(data string) (stop bool, err error)) error {
	rd := bufio.NewReaderSize(body, 64<<10)
	var line strings.Builder
	emit := func() (bool, error) {
		l := line.String()
		line.Reset()
		if !strings.HasPrefix(l, "data:") {
			return false, nil
		}
		return each(strings.TrimSpace(l[5:]))
	}
	for {
		r, _, err := rd.ReadRune()
		if err == nil && !lineBreak(r) {
			if line.Len() >= LineLimit {
				return tooLarge("one line", LineLimit)
			}
			line.WriteRune(r)
			continue
		}
		if err == nil {
			if r == '\r' {
				if next, _, perr := rd.ReadRune(); perr == nil && next != '\n' {
					_ = rd.UnreadRune()
				}
			}
			stop, ferr := emit()
			if ferr != nil || stop {
				return ferr
			}
			continue
		}
		if errors.Is(err, io.EOF) {
			if line.Len() > 0 {
				_, ferr := emit()
				return ferr
			}
			return nil
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		var py *PyError
		if errors.As(err, &py) && py.Type == "ResponseTooLarge" {
			return err
		}
		if cause := context.Cause(body.ctx); errors.Is(cause, errIdle) {
			err = fmt.Errorf("%w: %w", cause, err)
		}
		return classifyTransport(err, "read")
	}
}

func decodeObject(data string) (map[string]any, bool, error) {
	dec := json.NewDecoder(strings.NewReader(data))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, false, nil
	}
	if dec.More() {
		return nil, false, nil
	}
	obj, ok := v.(map[string]any)
	if !ok {
		return nil, false, &PyError{Type: "AttributeError", Msg: fmt.Sprintf("'%s' object has no attribute 'get'", pyTypeOfJSON(v))}
	}
	return obj, true, nil
}

func pyTypeOfJSON(v any) string {
	switch t := v.(type) {
	case string:
		return "str"
	case bool:
		return "bool"
	case nil:
		return "NoneType"
	case []any:
		return "list"
	case json.Number:
		if strings.ContainsAny(string(t), ".eE") {
			return "float"
		}
		return "int"
	}
	return "object"
}

func truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case bool:
		return t
	case string:
		return t != ""
	case json.Number:
		f, err := t.Float64()
		return err != nil || f != 0
	case []any:
		return len(t) > 0
	case map[string]any:
		return len(t) > 0
	}
	return true
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

func intCode(v any) (int, bool) {
	n, ok := v.(json.Number)
	if !ok || strings.ContainsAny(string(n), ".eE") {
		return 0, false
	}
	i, err := strconv.Atoi(string(n))
	return i, err == nil
}

// streamError is _raise_stream_error.
func streamError(chunk map[string]any) error {
	errv := chunk["error"]
	choices, _ := chunk["choices"].([]any)
	finishedInError := false
	if len(choices) > 0 {
		if c, ok := choices[0].(map[string]any); ok && c["finish_reason"] == "error" {
			finishedInError = true
		}
	}
	if !truthy(errv) && !finishedInError {
		return nil
	}
	details, _ := errv.(map[string]any)
	code := details["code"]
	status := 502
	if i, ok := intCode(code); ok && i >= 400 && i <= 599 {
		status = i
	} else if s, ok := code.(string); ok {
		if v, known := streamErrorCodeStatus()[s]; known {
			status = v
		}
	}
	var message string
	switch {
	case truthy(details["message"]):
		message = pyStr(details["message"])
	case str(errv) != "":
		message = str(errv)
	default:
		message = "the provider ended the stream with an error"
	}
	if s, ok := code.(string); ok && s != "" {
		message = s + ": " + message
	}
	return &ProviderHTTPError{StatusCode: status, ProviderMessage: message}
}

func pyStr(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case json.Number:
		return PyNumberStr(t)
	}
	return pyRepr(v)
}

func (m Model) streamOpenAI(ctx context.Context, r Request, yield func(Delta) error) error {
	url, err := m.apiURL("/chat/completions")
	if err != nil {
		return err
	}
	messages := openAIMessages(r.Messages)
	if m.Profile.CacheBreakpoints {
		messages = withCacheBreakpoints(messages)
	}
	payload := map[string]any{
		"model": m.ModelName, "messages": messages, "stream": true,
		"stream_options": map[string]any{"include_usage": true},
	}
	if len(r.Tools) > 0 {
		payload["tools"] = openAITools(r.Tools)
		payload["tool_choice"] = "auto"
	}
	if r.Temperature != nil {
		payload["temperature"] = *r.Temperature
	}
	if r.MaxTokens != 0 {
		payload["max_tokens"] = r.MaxTokens
	}
	fields, err := m.Profile.ReasoningFields(r.ReasoningEffort, r.ReasoningMaxTokens)
	if err != nil {
		return err
	}
	for k, v := range fields {
		payload[k] = v
	}
	body, _, err := m.send(ctx, url, payload)
	if err != nil {
		return err
	}
	defer func() { _ = body.Close() }()

	type buffered struct{ id, name, args string }
	toolCalls := map[int]*buffered{}
	var finalUsage *Usage
	finalCost := money.FromInt(0)
	return lines(ctx, body, func(data string) (bool, error) {
		if data == "[DONE]" {
			return true, nil
		}
		chunk, ok, err := decodeObject(data)
		if err != nil || !ok {
			return false, err
		}
		if err := streamError(chunk); err != nil {
			return false, err
		}
		usageData := chunk["usage"]
		hasUsage := truthy(usageData)
		if hasUsage {
			raw, _ := usageData.(map[string]any)
			u := UsageFromProvider(raw)
			finalUsage = &u
			if reported := ProviderReportedCost(raw); reported != nil {
				finalCost = *reported
			} else {
				finalCost = m.configuredCost(u)
			}
		}
		choices, _ := chunk["choices"].([]any)
		if len(choices) == 0 {
			if finalUsage != nil {
				return false, yield(Delta{Usage: finalUsage, Cost: finalCost})
			}
			return false, nil
		}
		choice, _ := choices[0].(map[string]any)
		delta, _ := choice["delta"].(map[string]any)
		finish := ""
		if truthy(choice["finish_reason"]) {
			finish = pyStr(choice["finish_reason"])
		}
		content := ""
		if truthy(delta["content"]) {
			content = str(delta["content"])
		}
		reasoning := ""
		for _, k := range []string{"reasoning_content", "reasoning", "thinking"} {
			if truthy(delta[k]) {
				reasoning = str(delta[k])
				break
			}
		}
		var tcDeltas []any
		if truthy(delta["tool_calls"]) {
			tcDeltas, _ = delta["tool_calls"].([]any)
		} else if truthy(delta["function_call"]) {
			tcDeltas = []any{map[string]any{"index": json.Number("0"), "function": delta["function_call"]}}
		}
		var snapshot []api.ToolCall
		if len(tcDeltas) > 0 {
			for _, d := range tcDeltas {
				tc, _ := d.(map[string]any)
				idx, _ := intCode(tc["index"])
				b, ok := toolCalls[idx]
				if !ok {
					b = &buffered{}
					toolCalls[idx] = b
				}
				if truthy(tc["id"]) {
					b.id = str(tc["id"])
				}
				fn, _ := tc["function"].(map[string]any)
				if truthy(fn["name"]) {
					b.name = str(fn["name"])
				}
				if truthy(fn["arguments"]) {
					b.args += str(fn["arguments"])
				}
			}
			keys := make([]int, 0, len(toolCalls))
			for k := range toolCalls {
				keys = append(keys, k)
			}
			sort.Ints(keys)
			for _, k := range keys {
				b := toolCalls[k]
				snapshot = append(snapshot, api.ToolCall{ID: b.id, Name: b.name, Arguments: b.args})
			}
		}
		var usage *Usage
		cost := money.FromInt(0)
		if hasUsage {
			usage, cost = finalUsage, finalCost
		}
		if content != "" || reasoning != "" || len(snapshot) > 0 || usage != nil || finish != "" {
			return false, yield(Delta{Content: content, Reasoning: reasoning, ToolCalls: snapshot, Usage: usage, Cost: cost, FinishReason: finish})
		}
		return false, nil
	})
}

func (m Model) streamAnthropic(ctx context.Context, r Request, yield func(Delta) error) error {
	if r.ReasoningEffort != "" || (r.ReasoningMaxTokens != nil && *r.ReasoningMaxTokens != 0) {
		return &domain.ReasoningSettingError{Msg: "the Anthropic transport does not take reasoning settings yet"}
	}
	url, err := m.apiURL("/messages")
	if err != nil {
		return err
	}
	system, turns := anthropicMessages(openAIMessages(r.Messages), func(msg string) { slog.WarnContext(ctx, msg) })
	maxTokens := r.MaxTokens
	if maxTokens == 0 {
		maxTokens = anthropicDefaultMaxTokens
	}
	payload := map[string]any{
		"model": m.ModelName, "messages": turns, "max_tokens": maxTokens, "stream": true,
		"cache_control": cacheBreakpoint(),
	}
	if system != "" {
		payload["system"] = system
	}
	if len(r.Tools) > 0 {
		payload["tools"] = anthropicTools(r.Tools)
		payload["tool_choice"] = map[string]any{"type": "auto"}
	}
	if r.Temperature != nil {
		payload["temperature"] = *r.Temperature
	}
	body, _, err := m.send(ctx, url, payload)
	if err != nil {
		return err
	}
	usageFields := map[string]any{}
	finish := ""
	var calls []*api.ToolCall
	atBlock := map[int]*api.ToolCall{}
	snapshot := func() []api.ToolCall {
		out := make([]api.ToolCall, len(calls))
		for i, c := range calls {
			out[i] = *c
		}
		return out
	}
	merge := func(v any) {
		if u, ok := v.(map[string]any); ok {
			for k, x := range u {
				usageFields[k] = x
			}
		}
	}
	err = lines(ctx, body, func(data string) (bool, error) {
		event, ok, err := decodeObject(data)
		if err != nil || !ok {
			return false, err
		}
		switch event["type"] {
		case "message_start":
			msg, _ := event["message"].(map[string]any)
			merge(msg["usage"])
		case "content_block_start":
			block, _ := event["content_block"].(map[string]any)
			if block["type"] == "tool_use" {
				call := &api.ToolCall{ID: str(block["id"]), Name: str(block["name"])}
				calls = append(calls, call)
				idx := len(calls) - 1
				if i, ok := intCode(event["index"]); ok {
					idx = i
				}
				atBlock[idx] = call
				return false, yield(Delta{ToolCalls: snapshot(), Cost: money.FromInt(0)})
			}
		case "content_block_delta":
			delta, _ := event["delta"].(map[string]any)
			switch delta["type"] {
			case "text_delta":
				if truthy(delta["text"]) {
					return false, yield(Delta{Content: str(delta["text"]), Cost: money.FromInt(0)})
				}
			case "thinking_delta":
				if truthy(delta["thinking"]) {
					return false, yield(Delta{Reasoning: str(delta["thinking"]), Cost: money.FromInt(0)})
				}
			case "input_json_delta":
				if truthy(delta["partial_json"]) {
					idx := -1
					if i, ok := intCode(event["index"]); ok {
						idx = i
					}
					if call := atBlock[idx]; call != nil {
						call.Arguments += str(delta["partial_json"])
						return false, yield(Delta{ToolCalls: snapshot(), Cost: money.FromInt(0)})
					}
				}
			}
		case "message_delta":
			merge(event["usage"])
			delta, _ := event["delta"].(map[string]any)
			if stop := delta["stop_reason"]; truthy(stop) {
				s := pyStr(stop)
				if mapped, ok := anthropicFinishReason()[s]; ok {
					s = mapped
				}
				finish = s
			}
		case "error":
			e, _ := event["error"].(map[string]any)
			status := 500
			if s, ok := anthropicStreamErrorStatus()[str(e["type"])]; ok {
				status = s
			}
			message := "stream error"
			if v, ok := e["message"]; ok {
				message = pyStr(v)
			}
			return false, &ProviderHTTPError{StatusCode: status, ProviderMessage: message}
		case "message_stop":
			return true, nil
		}
		return false, nil
	})
	_ = body.Close()
	if err != nil {
		return err
	}
	if len(usageFields) > 0 || finish != "" {
		d := Delta{FinishReason: finish, Cost: money.FromInt(0)}
		if len(usageFields) > 0 {
			u := UsageFromProvider(usageFields)
			d.Usage = &u
			d.Cost = m.configuredCost(u)
		}
		return yield(d)
	}
	return nil
}
