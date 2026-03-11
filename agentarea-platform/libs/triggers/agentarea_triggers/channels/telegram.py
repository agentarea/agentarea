"""Telegram channel adapter for outbound message delivery."""

import logging
from typing import Any

import httpx

from . import register_adapter

logger = logging.getLogger(__name__)

# Telegram message length limit
MAX_MESSAGE_LENGTH = 4096


class TelegramAdapter:
    """Send messages to Telegram via Bot API.

    Inbound is handled by the existing Telegram webhook parser.
    This adapter handles outbound: formatting events and sending via Bot API.

    Requires TELEGRAM_BOT_TOKEN in the channel config or environment.
    """

    def __init__(self, bot_token: str | None = None):
        self.bot_token = bot_token

    def format(self, event: dict[str, Any], presentation: str) -> str:
        """Format a workflow event for Telegram.

        Uses plain text with minimal markdown (Telegram MarkdownV2).
        """
        event_type = event.get("event_type", "")
        data = event.get("data", {})

        if event_type == "WorkflowCompleted":
            result = data.get("result", "Task completed.")
            return f"*Done* \u2014 {_escape_md(str(result))}"

        if event_type == "WorkflowFailed":
            error = data.get("error", "Unknown error")
            return f"\u274c *Failed* \u2014 {_escape_md(str(error))}"

        if event_type == "WorkflowCancelled":
            return "\u26d4 Task was cancelled."

        if event_type == "HumanApprovalRequested":
            question = data.get("question", "Approval needed")
            return f"\u2753 *Needs your input:*\n{_escape_md(str(question))}"

        if event_type == "HumanApprovalReceived":
            return "\u2705 Approval received, continuing..."

        if presentation == "concise":
            # Status events in concise mode
            if event_type == "WorkflowStarted":
                return "\u23f3 Working on it..."
            if event_type == "ToolCallStarted":
                tool = data.get("tool_name", "tool")
                return f"\ud83d\udd27 Using _{_escape_md(tool)}_..."
            if event_type in ("AgentDelegationStarted", "AgentDelegationCompleted"):
                agent = data.get("agent_name", "sub-agent")
                action = "Delegating to" if "Started" in event_type else "Received from"
                return f"\ud83e\udd16 {action} _{_escape_md(agent)}_"

        # Fallback for any unhandled event type in concise mode
        return f"\u2139\ufe0f {_escape_md(event_type)}"

    async def send(self, channel_config: dict[str, Any], message: str) -> None:
        """Send message via Telegram Bot API."""
        token = channel_config.get("bot_token") or self.bot_token
        if not token:
            logger.error("No Telegram bot token configured")
            return

        chat_id = channel_config.get("chat_id")
        if not chat_id:
            logger.error("No chat_id in channel config")
            return

        # Truncate if too long
        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[: MAX_MESSAGE_LENGTH - 20] + "\n\n_\\(truncated\\)_"

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "MarkdownV2",
        }

        # Reply to original message if available
        reply_to = channel_config.get("message_id")
        if reply_to:
            payload["reply_to_message_id"] = reply_to

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if not resp.is_success:
                    # Retry without markdown if parse fails
                    if resp.status_code == 400 and "parse" in resp.text.lower():
                        payload["parse_mode"] = ""
                        payload["text"] = _strip_md(message)
                        resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("Telegram send failed: %s", e)


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!\\"
    result = []
    for char in text:
        if char in special:
            result.append("\\")
        result.append(char)
    return "".join(result)


def _strip_md(text: str) -> str:
    """Remove markdown formatting for plain text fallback."""
    return text.replace("*", "").replace("_", "").replace("\\", "")


def create_telegram_adapter(bot_token: str | None = None) -> TelegramAdapter:
    """Create and register a Telegram adapter."""
    adapter = TelegramAdapter(bot_token)
    register_adapter("telegram", adapter)
    return adapter
