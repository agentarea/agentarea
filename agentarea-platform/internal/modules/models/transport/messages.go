package transport

import (
	"encoding/json"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

// msg is a chat message as Python's dicts hold it (ConversationEntry.as_message):
// role and content, then tool_call_id, name and tool_calls when set.
type msg = map[string]any

// openAIMessages renders the messages in the OpenAI chat shape.
func openAIMessages(ms []api.Message) []msg {
	out := make([]msg, len(ms))
	for i, m := range ms {
		var content any = m.Content
		if m.Parts != nil {
			parts := make([]any, len(m.Parts))
			for j, p := range m.Parts {
				switch p.Type {
				case "image_url":
					parts[j] = map[string]any{"type": "image_url", "image_url": map[string]any{"url": p.ImageURL}}
				case "file":
					parts[j] = map[string]any{"type": "file", "file": map[string]any{"filename": p.Filename, "file_data": p.FileData}}
				default:
					parts[j] = map[string]any{"type": p.Type, "text": p.Text}
				}
			}
			content = parts
		}
		o := msg{"role": m.Role, "content": content}
		if m.ToolCallID != "" {
			o["tool_call_id"] = m.ToolCallID
		}
		if m.Name != "" {
			o["name"] = m.Name
		}
		if len(m.ToolCalls) > 0 {
			calls := make([]any, len(m.ToolCalls))
			for j, tc := range m.ToolCalls {
				calls[j] = map[string]any{"id": tc.ID, "type": "function", "function": map[string]any{"name": tc.Name, "arguments": tc.Arguments}}
			}
			o["tool_calls"] = calls
		}
		out[i] = o
	}
	return out
}

// openAITools renders function tools as the loop hands them to the SDK.
func openAITools(ts []api.ToolDefinition) []any {
	out := make([]any, len(ts))
	for i, t := range ts {
		fn := map[string]any{"name": t.Name, "description": t.Description}
		if t.Parameters != nil {
			fn["parameters"] = t.Parameters
		} else {
			fn["parameters"] = map[string]any{}
		}
		out[i] = map[string]any{"type": "function", "function": fn}
	}
	return out
}

// cacheBreakpoint marks everything up to the block as cacheable for five minutes.
func cacheBreakpoint() map[string]any { return map[string]any{"type": "ephemeral"} }

func marked(m msg) msg {
	var parts []any
	switch c := m["content"].(type) {
	case string:
		if c == "" {
			return m
		}
		parts = []any{map[string]any{"type": "text", "text": c}}
	case []any:
		if len(c) == 0 {
			return m
		}
		last, ok := c[len(c)-1].(map[string]any)
		if !ok {
			return m
		}
		parts = append([]any(nil), c...)
		copied := map[string]any{}
		for k, v := range last {
			copied[k] = v
		}
		parts[len(parts)-1] = copied
	default:
		return m
	}
	last := parts[len(parts)-1].(map[string]any)
	last["cache_control"] = cacheBreakpoint()
	out := msg{}
	for k, v := range m {
		out[k] = v
	}
	out["content"] = parts
	return out
}

// withCacheBreakpoints marks the last system message and the last message.
func withCacheBreakpoints(ms []msg) []msg {
	out := append([]msg(nil), ms...)
	targets := map[int]bool{}
	if len(out) > 0 {
		targets[len(out)-1] = true
	}
	for i := len(out) - 1; i >= 0; i-- {
		if out[i]["role"] == "system" {
			targets[i] = true
			break
		}
	}
	for i := range targets {
		out[i] = marked(out[i])
	}
	return out
}

func textOf(content any) string {
	switch c := content.(type) {
	case string:
		return c
	case []any:
		var b strings.Builder
		for _, p := range c {
			if part, ok := p.(map[string]any); ok && part["type"] == "text" {
				if t, ok := part["text"].(string); ok {
					b.WriteString(t)
				}
			}
		}
		return b.String()
	case nil:
		return ""
	}
	raw, _ := json.Marshal(content)
	return string(raw)
}

func anthropicImage(part map[string]any) map[string]any {
	var url string
	switch img := part["image_url"].(type) {
	case map[string]any:
		url, _ = img["url"].(string)
	case string:
		url = img
	}
	if strings.HasPrefix(url, "data:") && strings.Contains(url, ";base64,") {
		header, data, _ := strings.Cut(url, ",")
		mediaType, _, _ := strings.Cut(strings.TrimPrefix(header, "data:"), ";")
		return map[string]any{"type": "image", "source": map[string]any{"type": "base64", "media_type": mediaType, "data": data}}
	}
	return map[string]any{"type": "image", "source": map[string]any{"type": "url", "url": url}}
}

// anthropicDocument is an OpenAI file part as a document block; the file is a base64 data URL.
func anthropicDocument(part map[string]any) map[string]any {
	file, _ := part["file"].(map[string]any)
	data, _ := file["file_data"].(string)
	header, payload, _ := strings.Cut(data, ",")
	mediaType, _, _ := strings.Cut(strings.TrimPrefix(header, "data:"), ";")
	return map[string]any{"type": "document", "source": map[string]any{"type": "base64", "media_type": mediaType, "data": payload}}
}

func anthropicBlocks(content any) []any {
	switch c := content.(type) {
	case string:
		if c == "" {
			return nil
		}
		return []any{map[string]any{"type": "text", "text": c}}
	case nil:
		return nil
	case map[string]any:
		content = []any{c}
	}
	list, ok := content.([]any)
	if !ok {
		return []any{map[string]any{"type": "text", "text": textOf(content)}}
	}
	var blocks []any
	for _, p := range list {
		part, ok := p.(map[string]any)
		switch {
		case !ok:
			blocks = append(blocks, map[string]any{"type": "text", "text": textOf(p)})
		case part["type"] == "image_url":
			blocks = append(blocks, anthropicImage(part))
		case part["type"] == "file":
			blocks = append(blocks, anthropicDocument(part))
		case part["type"] == "text":
			if t, _ := part["text"].(string); t != "" {
				blocks = append(blocks, map[string]any{"type": "text", "text": t})
			}
		default:
			blocks = append(blocks, part)
		}
	}
	return blocks
}

func anthropicToolUse(tc map[string]any, warn func(string)) map[string]any {
	fn, _ := tc["function"].(map[string]any)
	args, _ := fn["arguments"].(string)
	if args == "" {
		args = "{}"
	}
	input := map[string]any{}
	var parsed any
	if err := json.Unmarshal([]byte(args), &parsed); err != nil {
		warn("Tool call has arguments that are not JSON")
	} else if obj, ok := parsed.(map[string]any); ok {
		input = obj
	}
	id, _ := tc["id"].(string)
	name, _ := fn["name"].(string)
	return map[string]any{"type": "tool_use", "id": id, "name": name, "input": input}
}

// anthropicMessages is to_anthropic_messages: system text joined by blank
// lines, tool results as user tool_result blocks, consecutive same-role turns merged.
func anthropicMessages(ms []msg, warn func(string)) (string, []any) {
	var system []string
	var turns []map[string]any
	for _, m := range ms {
		role, _ := m["role"].(string)
		var blocks []any
		switch role {
		case "system":
			if t := textOf(m["content"]); t != "" {
				system = append(system, t)
			}
			continue
		case "tool":
			content, isStr := m["content"].(string)
			if !isStr {
				raw, _ := pyJSONDumps(m["content"])
				content = raw
			}
			id, _ := m["tool_call_id"].(string)
			blocks = []any{map[string]any{"type": "tool_result", "tool_use_id": id, "content": content}}
			role = "user"
		case "assistant":
			blocks = anthropicBlocks(m["content"])
			if calls, ok := m["tool_calls"].([]any); ok {
				for _, c := range calls {
					if tc, ok := c.(map[string]any); ok {
						blocks = append(blocks, anthropicToolUse(tc, warn))
					}
				}
			}
		default:
			role = "user"
			blocks = anthropicBlocks(m["content"])
		}
		if len(blocks) == 0 {
			continue
		}
		if n := len(turns); n > 0 && turns[n-1]["role"] == role {
			turns[n-1]["content"] = append(turns[n-1]["content"].([]any), blocks...)
		} else {
			turns = append(turns, map[string]any{"role": role, "content": blocks})
		}
	}
	out := make([]any, len(turns))
	for i, t := range turns {
		out[i] = t
	}
	return strings.Join(system, "\n\n"), out
}

// anthropicTools is to_anthropic_tools.
func anthropicTools(ts []api.ToolDefinition) []any {
	out := make([]any, len(ts))
	for i, t := range ts {
		var schema any = map[string]any{"type": "object", "properties": map[string]any{}}
		if len(t.Parameters) > 0 {
			schema = t.Parameters
		}
		out[i] = map[string]any{"name": t.Name, "description": t.Description, "input_schema": schema}
	}
	return out
}

// pyJSONDumps is json.dumps with its default separators and ensure_ascii.
func pyJSONDumps(v any) (string, error) {
	var b strings.Builder
	if err := pyDumps(&b, v); err != nil {
		return "", err
	}
	return b.String(), nil
}
