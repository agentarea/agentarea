"""Summarization middleware for context management.

Inspired by LangChain Deep Agents
Original work Copyright (c) LangChain, Inc. under MIT License
https://github.com/langchain-ai/langchain
"""

import logging
from typing import Any

from ..models.llm_model import LLMModel, LLMRequest

logger = logging.getLogger(__name__)


DEFAULT_SUMMARY_PROMPT = """<role>
Context Extraction Assistant
</role>

<primary_objective>
Your sole objective in this task is to extract the highest quality/most relevant context from the conversation history below.
</primary_objective>

<objective_information>
You're nearing the total number of input tokens you can accept, so you must extract the highest quality/most relevant pieces of information from your conversation history.
This context will then overwrite the conversation history presented below. Because of this, ensure the context you extract is only the most important information to your overall goal.
</objective_information>

<instructions>
The conversation history below will be replaced with the context you extract in this step. Because of this, you must do your very best to extract and record all of the most important context from the conversation history.
You want to ensure that you don't repeat any actions you've already completed, so the context you extract from the conversation history should be focused on the most important information to your overall goal.
</instructions>

The user will message you with the full message history you'll be extracting context from, to then replace. Carefully read over it all, and think deeply about what information is most important to your overall goal that should be saved.

With all of this in mind, please carefully read over the entire conversation history, and extract the most important and relevant context to replace it so that you can free up space in the conversation history.
Respond ONLY with the extracted context. Do not include any additional information, or text before or after the extracted context.

<messages>
Messages to summarize:
{messages}
</messages>"""


def count_tokens_approx(text: str) -> int:
    """Approximate token count (1 token ≈ 4 chars)."""
    return len(text) // 4


def count_messages_tokens(messages: list[dict]) -> int:
    """Count tokens in messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens_approx(content)
        # Count tool calls
        if "tool_calls" in msg:
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict):
                    total += count_tokens_approx(str(tc))
    return total


def format_messages_for_summary(messages: list[dict]) -> str:
    """Format messages for summary prompt."""
    parts = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, str) and content:
            parts.append(f"Message {i+1} ({role}): {content[:500]}")

        # Include tool calls info
        if "tool_calls" in msg and msg["tool_calls"]:
            tool_names = [tc.get("function", {}).get("name", "unknown")
                         for tc in msg["tool_calls"] if isinstance(tc, dict)]
            if tool_names:
                parts.append(f"  Tools called: {', '.join(tool_names)}")

    return "\n".join(parts)


class SummarizationMiddleware:
    """Auto-summarizes context using LLM when token limit exceeded.

    Inspired by LangChain Deep Agents implementation.
    """

    def __init__(
        self,
        model_provider: str = "ollama_chat",
        model_name: str = "qwen2.5:3b",
        endpoint_url: str | None = None,
        max_tokens_before_summary: int = 50_000,
        messages_to_keep: int = 6,
        summary_prompt: str = DEFAULT_SUMMARY_PROMPT,
    ):
        """Initialize summarization middleware.

        Args:
            model_provider: LLM provider for summarization
            model_name: Model name for summarization
            endpoint_url: Optional endpoint URL
            max_tokens_before_summary: Token threshold to trigger summarization
            messages_to_keep: Number of recent messages to preserve
            summary_prompt: Custom prompt template for summarization
        """
        self.max_tokens = max_tokens_before_summary
        self.keep_last = messages_to_keep
        self.summary_prompt = summary_prompt

        self.model = LLMModel(
            provider_type=model_provider,
            model_name=model_name,
            endpoint_url=endpoint_url,
        )

    async def before_llm_call(self, state: dict) -> dict[str, Any] | None:
        """Summarize old messages if token limit exceeded."""
        messages = state.get("messages", [])

        # Need at least keep_last + 2 messages to summarize (system + keep_last + old)
        if len(messages) <= self.keep_last + 1:
            return None

        token_count = count_messages_tokens(messages)

        if token_count <= self.max_tokens:
            return None

        # Separate system message, old messages, recent messages
        system_msg = None
        if messages and messages[0].get("role") == "system":
            system_msg = messages[0]
            messages = messages[1:]

        if len(messages) <= self.keep_last:
            return None

        recent = messages[-self.keep_last :]
        old = messages[: -self.keep_last]

        logger.info(
            f"Summarizing {len(old)} old messages (keeping last {self.keep_last}), "
            f"token count: {token_count} > {self.max_tokens}"
        )

        # Generate LLM-based summary
        try:
            summary_text = await self._generate_summary(old)
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            # Fallback to simple truncation
            summary_parts = []
            for msg in old[:20]:  # Max 20 messages
                role = msg.get("role", "unknown")
                content = str(msg.get("content", ""))[:200]
                summary_parts.append(f"{role}: {content}")
            summary_text = "\n".join(summary_parts)

        summary_msg = {
            "role": "system",
            "content": f"[Context Summary - {len(old)} messages]:\n{summary_text}\n[End Summary]",
        }

        new_messages = []
        if system_msg:
            new_messages.append(system_msg)
        new_messages.append(summary_msg)
        new_messages.extend(recent)

        new_token_count = count_messages_tokens(new_messages)

        logger.info(
            f"Summarization complete: {token_count} → {new_token_count} tokens "
            f"({len(old)} messages → summary)"
        )

        return {
            "messages": new_messages,
            "summarization_count": state.get("summarization_count", 0) + 1,
        }

    async def _generate_summary(self, messages: list[dict]) -> str:
        """Generate LLM-based summary of messages."""
        messages_text = format_messages_for_summary(messages)
        prompt = self.summary_prompt.format(messages=messages_text)

        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )

        response_stream = self.model.ainvoke_stream(request)
        summary = ""

        async for chunk in response_stream:
            if chunk.content:
                summary += chunk.content

        return summary.strip()

    async def after_llm_call(self, state: dict, response: Any) -> dict[str, Any] | None:
        return None

    async def before_tool_call(
        self, tool_call: dict, state: dict
    ) -> tuple[dict, dict[str, Any] | None]:
        return tool_call, None

    async def after_tool_call(
        self, tool_call: dict, result: Any, state: dict
    ) -> tuple[Any, dict[str, Any] | None]:
        return result, None
