"""Context window management for agent execution workflows."""

from __future__ import annotations

import json
from typing import Any

from agentarea_agents_sdk.skills import SkillContextGuard

from .constants import (
    CONTEXT_COMPACT_THRESHOLD,
    CONTEXT_RESERVE_FOR_OUTPUT,
    CONTEXT_WARNING_THRESHOLD,
    DEFAULT_CONTEXT_WINDOW,
    TOKENS_PER_MESSAGE_OVERHEAD,
)


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Uses character-based approximation (~4 chars per token for English text).
    Sufficient for context window management decisions.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_tokens_for_messages(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of messages including overhead.

    Accounts for per-message overhead and serializes tool calls to count their tokens.
    """
    total = 0
    for message in messages:
        total += TOKENS_PER_MESSAGE_OVERHEAD

        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            # Content can be a list of blocks (e.g. Anthropic format)
            for block in content:
                if isinstance(block, dict):
                    total += estimate_tokens(json.dumps(block))
                elif isinstance(block, str):
                    total += estimate_tokens(block)

        tool_calls = message.get("tool_calls")
        if tool_calls:
            total += estimate_tokens(json.dumps(tool_calls))

        # tool_result role messages (OpenAI style use role=tool)
        tool_call_id = message.get("tool_call_id")
        if tool_call_id:
            total += estimate_tokens(tool_call_id)

    return total


def validate_tool_pairs(messages: list[dict[str, Any]]) -> bool:
    """Ensure no orphaned tool_results exist.

    Every tool_result (role=tool) must have a matching tool_use (tool call id)
    in a preceding assistant message.
    """
    # Collect all tool call ids from assistant messages
    assistant_tool_call_ids: set[str] = set()
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            tool_calls = message.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc_id = tc.get("id")
                        if tc_id:
                            assistant_tool_call_ids.add(tc_id)

    # Check every tool result references a known tool call id
    for message in messages:
        role = message.get("role")
        if role == "tool":
            tool_call_id = message.get("tool_call_id")
            if tool_call_id and tool_call_id not in assistant_tool_call_ids:
                return False

    return True


def find_compaction_boundary(messages: list[dict[str, Any]], keep_recent: int) -> int:
    """Find a safe index to split messages for compaction.

    Always keeps the first message (system prompt) and the last `keep_recent` messages.
    Does not split in the middle of a tool call / tool result pair.

    Returns the index of the first message to remove (exclusive end of kept prefix),
    or 0 if nothing safe to compact.
    """
    if len(messages) <= keep_recent + 1:
        # Not enough messages to compact (keep system + recent)
        return 0

    # The compactable range is messages[1 .. len-keep_recent]
    # We want to find the largest boundary index in that range that doesn't
    # break tool pairs.
    #
    # Strategy: scan from the end of the compactable range backward until
    # we land on a safe boundary (not in the middle of a tool exchange).

    compactable_end = len(messages) - keep_recent  # exclusive

    # Build a set of tool_call_ids introduced in each range
    # A safe boundary is one where no tool result in messages[boundary..compactable_end]
    # references a tool call in messages[1..boundary].

    # Collect tool_call_ids produced in messages[1..compactable_end]
    # and find the rightmost split that doesn't orphan any tool result.

    # Try boundary points from largest to smallest
    for boundary in range(compactable_end, 1, -1):
        # messages[0] is system prompt (kept), messages[1..boundary-1] are removed,
        # messages[boundary..] are kept.
        # Check: no tool result in messages[boundary..] references a tool call
        # that only exists in messages[1..boundary-1].

        kept_suffix = messages[boundary:]
        removed_section = messages[1:boundary]

        # Never compact messages containing activated skill content
        if any(SkillContextGuard.is_protected(msg) for msg in removed_section):
            continue

        # tool call ids in removed section
        removed_tool_ids: set[str] = set()
        for msg in removed_section:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        removed_tool_ids.add(tc["id"])

        # Check if any kept message references a removed tool call id
        orphan_found = False
        for msg in kept_suffix:
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id and tc_id in removed_tool_ids:
                    orphan_found = True
                    break

        if not orphan_found and boundary > 1:
            return boundary

    return 0


class ContextWindowManager:
    """Manages context window usage tracking and compaction decisions.

    Mirrors BudgetTracker pattern from helpers.py.
    """

    def __init__(self, context_window: int | None = None) -> None:
        raw_limit = context_window or DEFAULT_CONTEXT_WINDOW
        # Reserve a fraction for model output
        self._effective_limit = int(raw_limit * (1.0 - CONTEXT_RESERVE_FOR_OUTPUT))
        self._current_tokens: int = 0
        self._warning_sent: bool = False
        self._compaction_count: int = 0

    def update_usage(self, prompt_tokens: int) -> None:
        """Record actual prompt token count from LLM response."""
        self._current_tokens = prompt_tokens

    def estimate_usage(self, messages: list[dict[str, Any]]) -> int:
        """Estimate tokens for a message list and update internal state."""
        estimated = estimate_tokens_for_messages(messages)
        self._current_tokens = estimated
        return estimated

    def get_usage_ratio(self) -> float:
        """Return current token usage as a ratio of the effective limit."""
        if self._effective_limit <= 0:
            return 1.0
        return self._current_tokens / self._effective_limit

    def needs_compaction(self) -> bool:
        """Return True if token usage is at or above the compaction threshold."""
        return self.get_usage_ratio() >= CONTEXT_COMPACT_THRESHOLD

    def should_warn(self) -> bool:
        """Return True if usage is at or above warning threshold and warning not yet sent."""
        return self.get_usage_ratio() >= CONTEXT_WARNING_THRESHOLD and not self._warning_sent

    def mark_warning_sent(self) -> None:
        """Record that a context warning has been emitted."""
        self._warning_sent = True

    def mark_compacted(self) -> None:
        """Record that a compaction was performed."""
        self._compaction_count += 1
        self._warning_sent = False  # Reset so warning can fire again after compaction

    @property
    def compaction_count(self) -> int:
        """Number of compactions performed so far."""
        return self._compaction_count

    def get_status(self) -> dict[str, Any]:
        """Return a full status dictionary."""
        return {
            "current_tokens": self._current_tokens,
            "effective_limit": self._effective_limit,
            "usage_ratio": self.get_usage_ratio(),
            "needs_compaction": self.needs_compaction(),
            "warning_sent": self._warning_sent,
            "compaction_count": self._compaction_count,
            "compact_threshold": CONTEXT_COMPACT_THRESHOLD,
            "warning_threshold": CONTEXT_WARNING_THRESHOLD,
        }
