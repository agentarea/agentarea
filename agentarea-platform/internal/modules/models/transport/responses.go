package transport

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

// responsesInput renders the conversation as Responses API input items; a
// system message is a developer message, as the Codex CLI sends its instructions.
func responsesInput(ms []api.Message) []any {
	input := []any{}
	for _, m := range ms {
		switch m.Role {
		case "system", "developer":
			input = append(input, map[string]any{"type": "message", "role": "developer",
				"content": []any{map[string]any{"type": "input_text", "text": m.Content}}})
		case "tool":
			input = append(input, map[string]any{"type": "function_call_output", "call_id": m.ToolCallID, "output": m.Content})
		case "assistant":
			if m.Content != "" {
				input = append(input, map[string]any{"type": "message", "role": "assistant",
					"content": []any{map[string]any{"type": "output_text", "text": m.Content}}})
			}
			for _, tc := range m.ToolCalls {
				input = append(input, map[string]any{"type": "function_call", "call_id": tc.ID, "name": tc.Name, "arguments": tc.Arguments})
			}
		default:
			parts := []any{}
			if m.Parts != nil {
				for _, p := range m.Parts {
					if p.Type == "image_url" {
						parts = append(parts, map[string]any{"type": "input_image", "image_url": p.ImageURL})
					} else {
						parts = append(parts, map[string]any{"type": "input_text", "text": p.Text})
					}
				}
			} else {
				parts = append(parts, map[string]any{"type": "input_text", "text": m.Content})
			}
			input = append(input, map[string]any{"type": "message", "role": "user", "content": parts})
		}
	}
	return input
}

func responsesTools(ts []api.ToolDefinition) []any {
	out := make([]any, len(ts))
	for i, t := range ts {
		params := t.Parameters
		if params == nil {
			params = map[string]any{"type": "object", "properties": map[string]any{}}
		}
		out[i] = map[string]any{"type": "function", "name": t.Name, "description": t.Description, "parameters": params, "strict": false}
	}
	return out
}

// responsesUsage maps a Responses usage block onto the chat-completions names.
func responsesUsage(u map[string]any) map[string]any {
	out := map[string]any{"prompt_tokens": u["input_tokens"], "completion_tokens": u["output_tokens"]}
	if t, ok := u["total_tokens"]; ok {
		out["total_tokens"] = t
	}
	if d := fields(u["input_tokens_details"]); d != nil {
		out["prompt_tokens_details"] = map[string]any{"cached_tokens": d["cached_tokens"]}
	}
	return out
}

func responsesError(e map[string]any, fallback string) error {
	code := str(e["code"])
	message := str(e["message"])
	if message == "" {
		message = fallback
	}
	if code != "" {
		message = code + ": " + message
	}
	status := 502
	if s, ok := streamErrorCodeStatus()[code]; ok {
		status = s
	}
	return &ProviderHTTPError{StatusCode: status, ProviderMessage: message}
}

func (m Model) streamResponses(ctx context.Context, r Request, yield func(Delta) error) error {
	url, err := m.apiURL("/responses")
	if err != nil {
		return err
	}
	payload := map[string]any{"model": m.ModelName, "input": responsesInput(r.Messages), "store": false, "stream": true}
	if len(r.Tools) > 0 {
		payload["tools"] = responsesTools(r.Tools)
		payload["tool_choice"] = "auto"
		payload["parallel_tool_calls"] = false
	}
	if r.ReasoningMaxTokens != nil && *r.ReasoningMaxTokens != 0 {
		return &domain.ReasoningSettingError{Msg: "this provider takes a reasoning level (reasoning_effort), not a token budget"}
	}
	if r.ReasoningEffort != "" {
		payload["reasoning"] = map[string]any{"effort": r.ReasoningEffort, "summary": "auto"}
	}
	if m.Profile.Auth != domain.AuthChatGPT {
		if r.Temperature != nil {
			payload["temperature"] = *r.Temperature
		}
		if r.MaxTokens != 0 {
			payload["max_output_tokens"] = r.MaxTokens
		}
	}
	body, _, err := m.send(ctx, url, payload)
	if err != nil {
		return err
	}
	defer func() { _ = body.Close() }()

	var calls []api.ToolCall
	return lines(ctx, body, func(data string) (bool, error) {
		event, ok, err := decodeObject(data)
		if err != nil || !ok {
			return false, err
		}
		switch event["type"] {
		case "response.output_text.delta":
			if d := str(event["delta"]); d != "" {
				return false, yield(Delta{Content: d, Cost: money.FromInt(0)})
			}
		case "response.reasoning_summary_text.delta", "response.reasoning_text.delta":
			if d := str(event["delta"]); d != "" {
				return false, yield(Delta{Reasoning: d, Cost: money.FromInt(0)})
			}
		case "response.output_item.done":
			item := fields(event["item"])
			if item["type"] == "function_call" {
				calls = append(calls, api.ToolCall{ID: str(item["call_id"]), Name: str(item["name"]), Arguments: str(item["arguments"])})
				return false, yield(Delta{ToolCalls: append([]api.ToolCall(nil), calls...), Cost: money.FromInt(0)})
			}
		case "response.completed", "response.incomplete":
			resp := fields(event["response"])
			finish := "stop"
			if len(calls) > 0 {
				finish = "tool_calls"
			}
			if event["type"] == "response.incomplete" {
				finish = "length"
				if reason := str(fields(resp["incomplete_details"])["reason"]); reason == "content_filter" {
					finish = "content_filter"
				}
			}
			d := Delta{FinishReason: finish, Cost: money.FromInt(0)}
			if raw := fields(resp["usage"]); raw != nil {
				u := UsageFromProvider(responsesUsage(raw))
				d.Usage = &u
				d.Cost = m.configuredCost(u)
			}
			return true, yield(d)
		case "response.failed":
			return false, responsesError(fields(fields(event["response"])["error"]), "the provider failed the response")
		case "error":
			e := fields(event["error"])
			if e == nil {
				e = event
			}
			return false, responsesError(e, "stream error")
		}
		return false, nil
	})
}
