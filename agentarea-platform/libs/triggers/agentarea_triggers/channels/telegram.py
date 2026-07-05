"""Telegram channel adapter for outbound message delivery."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from . import register_adapter

if TYPE_CHECKING:
    from agentarea_common.infrastructure.secret_manager import BaseSecretManager

logger = logging.getLogger(__name__)

# Telegram message length limit
MAX_MESSAGE_LENGTH = 4096


class TelegramAdapter:
    """Send messages to Telegram via Bot API.

    Inbound is handled by the existing Telegram webhook parser.
    This adapter handles outbound: formatting events and sending via Bot API.

    Credentials (bot_token) are resolved from the secret store via
    channel_config["secret_key"]. The secret store holds a JSON blob
    like {"bot_token": "123:ABC"}.
    """

    def __init__(self, secret_manager: BaseSecretManager | None = None):
        self._secret_manager = secret_manager

    def format(self, event: dict[str, Any], presentation: str) -> str:
        """Format a workflow event for Telegram.

        Uses plain text with minimal markdown (Telegram MarkdownV2).
        """
        event_type = event.get("event_type", "")
        data = event.get("data", {})

        if event_type == "WorkflowCompleted":
            result = data.get("result") or data.get("final_response") or ""
            return _escape_md(str(result))

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
        """Send message via Telegram Bot API.

        Resolves bot_token from the secret store using channel_config["secret_key"].
        """
        token = await self._resolve_bot_token(channel_config)
        if not token:
            logger.error("No Telegram bot token — set secret_key in channel_origin")
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

        # Reply to original message if available. Use allow_sending_without_reply
        # so a stale/deleted/unknown message_id never fails the whole delivery —
        # Telegram returns 400 "message to be replied not found" otherwise, which
        # DLQs the reply and the user sees nothing.
        reply_to = channel_config.get("message_id")
        if reply_to:
            payload["reply_to_message_id"] = reply_to
            payload["allow_sending_without_reply"] = True

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

    async def _resolve_bot_token(self, channel_config: dict[str, Any]) -> str | None:
        """Resolve bot token from the secret store.

        Secret name is derived: channel_cred:{type}:{trigger_id}
        """
        if not self._secret_manager:
            logger.error("No secret_manager configured on TelegramAdapter")
            return None

        trigger_id = channel_config.get("trigger_id")
        if not trigger_id:
            logger.error("No trigger_id in channel_config — cannot resolve credentials")
            return None

        secret_name = f"channel_cred:{channel_config.get('type', 'telegram')}:{trigger_id}"
        raw = await self._secret_manager.get_secret(secret_name)
        if not raw:
            logger.error("Channel credentials not found for trigger %s", trigger_id)
            return None

        creds = json.loads(raw)
        return creds.get("bot_token")


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


def create_telegram_adapter(
    secret_manager: BaseSecretManager | None = None,
) -> TelegramAdapter:
    """Create and register a Telegram adapter."""
    adapter = TelegramAdapter(secret_manager=secret_manager)
    register_adapter("telegram", adapter)
    return adapter
