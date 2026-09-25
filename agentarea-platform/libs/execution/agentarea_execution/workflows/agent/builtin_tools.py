"""Schemas of the tools every agent run is given by the workflow itself."""

from typing import Any


def completion_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "completion",
            "description": (
                "Finish the task and send your response to the user. "
                "The 'result' parameter is the message the user will see — "
                "write it as a complete, helpful answer (not a summary or status). "
                "You MUST call this tool when you are done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "Your complete response to the user. This is what they will read.",
                    },
                    "artifacts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 1000,
                        "description": (
                            "Workspace-relative paths of every file the response delivers, "
                            "for example reports/result.pdf. They are saved for the user on "
                            "completion. Use an empty list only when the response promises "
                            "no files."
                        ),
                    },
                },
                "required": ["result", "artifacts"],
            },
        },
    }


def request_user_input_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "request_user_input",
            "description": (
                "Ask the user for missing information and pause this task until "
                "they reply. Use this instead of completion when the task cannot "
                "continue without user input. Optional choices may be supplied for "
                "single-select questions; free-text replies are allowed by default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "The exact question to show to the user for a simple "
                            "single-question prompt. For rich forms, use questions."
                        ),
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": ("Optional answer choices. Omit for a free-text question."),
                    },
                    "questions": {
                        "type": "array",
                        "description": (
                            "Optional structured form fields. Use this when you need "
                            "multiple answers, typed inputs, or secret inputs."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": (
                                        "Stable field identifier returned with the answer."
                                    ),
                                },
                                "question": {
                                    "type": "string",
                                    "description": "Field label/question shown to the user.",
                                },
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "text",
                                        "textarea",
                                        "select",
                                        "multiselect",
                                        "boolean",
                                        "number",
                                        "secret",
                                    ],
                                    "description": (
                                        "Input type. Use secret for API keys, tokens, "
                                        "passwords, and session strings."
                                    ),
                                },
                                "required": {"type": "boolean"},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "secret_name": {
                                    "type": "string",
                                    "description": (
                                        "Suggested workspace secret name for secret fields."
                                    ),
                                },
                            },
                            "required": ["id", "question"],
                        },
                    },
                    "allow_custom_response": {
                        "type": "boolean",
                        "description": (
                            "Whether the user may provide a free-text answer outside "
                            "the supplied options. Defaults to true."
                        ),
                    },
                },
            },
        },
    }


def recall_history_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "recall_history",
            "description": (
                "Recall context from past executions of this task. "
                "Use when you need information that may have been compacted "
                "out of the current conversation, or to review what happened "
                "in earlier execution attempts. Supports grep to search stored history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search query to describe what you're looking for",
                    },
                    "event_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by event types (e.g. ToolCallCompleted, LLMCallCompleted)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max events to return (default 20)",
                    },
                    "grep": {
                        "type": "string",
                        "description": "Regex pattern to search stored message history (searches MinIO history chunks)",
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "Filter stored history to messages from a specific tool",
                    },
                },
            },
        },
    }


def read_tool_output_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "read_tool_output",
            "description": (
                "Read a previously stored tool output. Use when you see "
                "'[Output stored as ...]' in a tool result and need the full content. "
                "Supports grep filtering and head/tail slicing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "output_id": {
                        "type": "string",
                        "description": "The output ID from the stored result reference",
                    },
                    "grep": {
                        "type": "string",
                        "description": "Filter lines matching this regex pattern",
                    },
                    "head": {
                        "type": "integer",
                        "description": "Return only first N lines",
                    },
                    "tail": {
                        "type": "integer",
                        "description": "Return only last N lines",
                    },
                },
                "required": ["output_id"],
            },
        },
    }
