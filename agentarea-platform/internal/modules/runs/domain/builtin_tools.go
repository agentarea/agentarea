package domain

import "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"

// WaitMinSeconds is the shortest wait the wait tool accepts.
const WaitMinSeconds = 1

type obj = map[string]any

// CompletionTool is the completion tool with the interaction contract's outcome.
func CompletionTool() api.ToolDefinition {
	return api.ToolDefinition{
		Name: ToolCompletion,
		Description: "Finish the task and send your response to the user. " +
			"The 'result' parameter is the message the user will see — " +
			"write it as a complete, helpful answer (not a summary or status). " +
			"You MUST call this tool when you are done.",
		Parameters: obj{
			"type": "object",
			"properties": obj{
				"result": obj{"type": "string", "description": "Your complete response to the user. This is what they will read."},
				"artifacts": obj{
					"type": "array", "items": obj{"type": "string"}, "maxItems": 1000,
					"description": "Files outside outputs/ the response also delivers, as " +
						"workspace-relative paths such as reports/result.pdf. Everything " +
						"in outputs/ is delivered without being listed.",
				},
				"outcome": obj{
					"type": "string", "enum": []any{"completed", "blocked"},
					"description": "Use blocked only for an actual unmet prerequisite after attempting " +
						"available autonomous alternatives. Explain what is missing in result. " +
						"Unavailable questions alone are not a reason to stop.",
				},
			},
			"required": []any{"result"},
		},
	}
}

// RequestUserInputTool asks the user and pauses the task.
func RequestUserInputTool() api.ToolDefinition {
	return api.ToolDefinition{
		Name: ToolRequestUserInput,
		Description: "Ask the user for missing information and pause this task until " +
			"they reply. Use this instead of completion when the task cannot " +
			"continue without user input. Optional choices may be supplied for " +
			"single-select questions; free-text replies are allowed by default.",
		Parameters: obj{
			"type": "object",
			"properties": obj{
				"question": obj{"type": "string", "description": "The exact question to show to the user for a simple " +
					"single-question prompt. For rich forms, use questions."},
				"options": obj{"type": "array", "items": obj{"type": "string"}, "description": "Optional answer choices. Omit for a free-text question."},
				"questions": obj{
					"type": "array",
					"description": "Optional structured form fields. Use this when you need " +
						"multiple answers, typed inputs, or secret inputs.",
					"items": obj{
						"type": "object",
						"properties": obj{
							"id":       obj{"type": "string", "description": "Stable field identifier returned with the answer."},
							"question": obj{"type": "string", "description": "Field label/question shown to the user."},
							"type": obj{
								"type": "string",
								"enum": []any{"text", "textarea", "select", "multiselect", "boolean", "number", "secret"},
								"description": "Input type. Use secret for API keys, tokens, " +
									"passwords, and session strings.",
							},
							"required":    obj{"type": "boolean"},
							"options":     obj{"type": "array", "items": obj{"type": "string"}},
							"secret_name": obj{"type": "string", "description": "Suggested workspace secret name for secret fields."},
						},
						"required": []any{"id", "question"},
					},
				},
				"allow_custom_response": obj{"type": "boolean", "description": "Whether the user may provide a free-text answer outside " +
					"the supplied options. Defaults to true."},
				"surface_id": obj{"type": "string", "description": "Bind required non-secret answers to an already emitted A2UI surface. " +
					"Action context keys must match question IDs. Omit for native input forms."},
			},
		},
	}
}

// RecallHistoryTool recalls compacted or earlier context.
func RecallHistoryTool() api.ToolDefinition {
	return api.ToolDefinition{
		Name: ToolRecallHistory,
		Description: "Recall context from past executions of this task. " +
			"Use when you need information that may have been compacted " +
			"out of the current conversation, or to review what happened " +
			"in earlier execution attempts. Supports grep to search stored history.",
		Parameters: obj{
			"type": "object",
			"properties": obj{
				"query":       obj{"type": "string", "description": "Optional search query to describe what you're looking for"},
				"event_types": obj{"type": "array", "items": obj{"type": "string"}, "description": "Filter by event types, dotted: e.g. tool.result, llm.call.completed, message.received"},
				"limit":       obj{"type": "integer", "description": "Max events to return (default 20)"},
				"grep":        obj{"type": "string", "description": "Regex pattern to search stored message history (searches MinIO history chunks)"},
				"tool_name":   obj{"type": "string", "description": "Filter stored history to messages from a specific tool"},
			},
		},
	}
}

// ReadToolOutputTool reads an offloaded tool output.
func ReadToolOutputTool() api.ToolDefinition {
	return api.ToolDefinition{
		Name: ToolReadToolOutput,
		Description: "Read a previously stored tool output. Use when you see " +
			"'[Output stored as ...]' in a tool result and need the full content. " +
			"Supports grep filtering and head/tail slicing.",
		Parameters: obj{
			"type": "object",
			"properties": obj{
				"output_id": obj{"type": "string", "description": "The output ID from the stored result reference"},
				"grep":      obj{"type": "string", "description": "Filter lines matching this regex pattern"},
				"head":      obj{"type": "integer", "description": "Return only first N lines"},
				"tail":      obj{"type": "integer", "description": "Return only last N lines"},
			},
			"required": []any{"output_id"},
		},
	}
}

// WaitTool holds the task for a while without holding anything else.
func WaitTool() api.ToolDefinition {
	return api.ToolDefinition{
		Name: ToolWait,
		Description: "Pause this task for a number of seconds, then continue. Nothing is held " +
			"while it waits, not a worker and not the sandbox, and the wait survives " +
			"restarts, so it can run for minutes, hours or days. Use it whenever " +
			"something should happen later: the user asks for something in some " +
			"minutes or at a given time (wait until then, then do it and reply), or " +
			"you poll an asynchronous job such as a video render. Never wait with " +
			"sleep, a timer or a background process in the shell: a shell command " +
			"holds the user off until it returns, and its background processes stop " +
			"when it does. A user message or a pause ends the wait early; the result " +
			"says how long you waited and why it ended, so answer the message and " +
			"then wait out the rest.",
		Parameters: obj{
			"type": "object",
			"properties": obj{
				"seconds": obj{"type": "integer", "minimum": WaitMinSeconds, "description": "How long to wait. For a moment in time, the seconds from now until it."},
				"reason":  obj{"type": "string", "description": "What you are waiting for; shown to the user."},
			},
			"required": []any{"seconds", "reason"},
		},
	}
}

// ActivateSkillTool loads a skill's full instructions; the enum lists the skills.
func ActivateSkillTool(skills []api.Skill) api.ToolDefinition {
	names := make([]any, 0, len(skills))
	for _, s := range skills {
		names = append(names, s.Name)
	}
	return api.ToolDefinition{
		Name:        ToolActivateSkill,
		Description: "Load full instructions for a skill by name.",
		Parameters: obj{
			"type": "object",
			"properties": obj{
				"skill_name": obj{"type": "string", "description": "Name of the skill to activate from the available skills catalog", "enum": names},
			},
			"required": []any{"skill_name"},
		},
	}
}

// LoadToolsTool reveals searchable OpenAPI operations.
func LoadToolsTool() api.ToolDefinition {
	return api.ToolDefinition{
		Name: ToolLoadTools,
		Description: "Load full schemas for operations listed in 'Available OpenAPI " +
			"Operations'. Pass the exact operation names you need; after this " +
			"call those operations become callable as regular tools.",
		Parameters: obj{
			"type": "object",
			"properties": obj{
				"tool_names": obj{"type": "array", "items": obj{"type": "string"}, "description": "Exact operation names from the catalog."},
			},
			"required": []any{"tool_names"},
		},
	}
}

// ActivateToolSourceTool opens a source of the dynamic catalog.
func ActivateToolSourceTool(providers []api.ToolProvider, activated []string) api.ToolDefinition {
	var names []any
	seen := map[string]bool{}
	for _, p := range providers {
		if !seen[p.Name] && !contains(activated, p.Name) {
			seen[p.Name] = true
			names = append(names, p.Name)
		}
	}
	sortAny(names)
	source := obj{"type": "string", "description": "Name of the tool source to activate", "enum": nil}
	if len(names) > 0 {
		source["enum"] = names
	}
	return api.ToolDefinition{
		Name: ToolActivateToolSource,
		Description: "Activate a tool source to load its tools into the current session. " +
			"Use this when you need tools from a source listed in Available Tool Sources.",
		Parameters: obj{"type": "object", "properties": obj{"source_name": source}, "required": []any{"source_name"}},
	}
}

func sortAny(xs []any) {
	for i := 1; i < len(xs); i++ {
		for j := i; j > 0 && xs[j].(string) < xs[j-1].(string); j-- {
			xs[j], xs[j-1] = xs[j-1], xs[j]
		}
	}
}

// DisclosedTools keeps the tools policy would let the model call; tools that
// need approval stay offered (filter_disclosed_tools).
func DisclosedTools(cfg *api.RunConfig, tools []api.ToolDefinition) []api.ToolDefinition {
	out := make([]api.ToolDefinition, 0, len(tools))
	for _, t := range tools {
		if t.Name == "" {
			continue
		}
		if ControlFlowTool(t.Name) {
			out = append(out, t)
			continue
		}
		if action, _ := DecideToolPolicy(cfg.Policy, t.Name, NamesFor(cfg, t.Name)); action != ToolDeny {
			out = append(out, t)
		}
	}
	return out
}
