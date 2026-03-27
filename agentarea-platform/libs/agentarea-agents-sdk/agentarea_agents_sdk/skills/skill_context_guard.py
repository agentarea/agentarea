"""Guards skill content from context window compaction."""

from typing import Any

# Tool names whose results must never be compacted
PROTECTED_TOOL_NAMES = frozenset({"activate_skill"})

# Fallback: content tag detection (defense in depth)
SKILL_CONTENT_TAG = "<skill_content"


class SkillContextGuard:
    """Identifies messages containing activated skill content.

    Used by ContextWindowManager to exempt skill instructions
    from compaction. Two detection methods (defense in depth):
    1. Tool name: messages with name="activate_skill"
    2. Content tag: messages containing <skill_content>
    """

    @staticmethod
    def is_protected(message: dict[str, Any]) -> bool:
        """Check if a message should be protected from compaction."""
        msg_name = message.get("name", "")
        if msg_name in PROTECTED_TOOL_NAMES:
            return True

        content = message.get("content", "")
        if isinstance(content, str) and SKILL_CONTENT_TAG in content:
            return True

        return False

    @staticmethod
    def count_protected(messages: list[dict[str, Any]]) -> int:
        """Count protected skill messages in a message list."""
        return sum(1 for m in messages if SkillContextGuard.is_protected(m))
