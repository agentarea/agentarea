"""Channel event type registry and trigger catalog.

Maps each webhook channel to its supported event types.
Used for event filtering on triggers and for the frontend event selector.

Also provides TRIGGER_CATALOG — the single source of truth for available
trigger types, served to the frontend via GET /triggers/catalog.
"""

from typing import Any

# ── Trigger catalog ───────────────────────────────────────────────
# Each entry defines a trigger type available in the UI.
# Frontend fetches this via API — never hardcodes trigger types.

TRIGGER_CATALOG: list[dict[str, Any]] = [
    {
        "id": "cron",
        "name": "Cron",
        "icon": "\u23f0",
        "description": "Run your agent on a schedule",
        "kind": "schedule",
        "backend_type": "cron",
    },
    {
        "id": "telegram",
        "name": "Telegram",
        "icon": "\u2708\ufe0f",
        "description": "Connect a Telegram bot to your agent",
        "kind": "messaging",
        "backend_type": "webhook",
        "webhook_type": "telegram",
        "default_methods": ["POST"],
        "credential_fields": [
            {"key": "bot_token", "label": "Bot Token", "placeholder": "Token from @BotFather"},
        ],
    },
    {
        "id": "slack",
        "name": "Slack",
        "icon": "\U0001f4ac",
        "description": "Receive Slack messages and events",
        "kind": "messaging",
        "backend_type": "webhook",
        "webhook_type": "slack",
        "default_methods": ["POST"],
        "credential_fields": [
            {"key": "signing_secret", "label": "Signing Secret", "placeholder": "Your Slack app's signing secret"},
        ],
    },
    {
        "id": "discord",
        "name": "Discord",
        "icon": "\U0001f3ae",
        "description": "Receive Discord messages and interactions",
        "kind": "messaging",
        "backend_type": "webhook",
        "webhook_type": "discord",
        "default_methods": ["POST"],
        "credential_fields": [
            {"key": "public_key", "label": "Application Public Key", "placeholder": "Your Discord app's public key"},
        ],
    },
    {
        "id": "email",
        "name": "Email",
        "icon": "\U0001f4e7",
        "description": "Trigger agent via email",
        "kind": "messaging",
        "backend_type": "webhook",
        "webhook_type": "gmail",
        "default_methods": ["POST"],
    },
    {
        "id": "webhook",
        "name": "Webhook",
        "icon": "\U0001f517",
        "description": "Generic HTTP webhook for any integration",
        "kind": "event",
        "backend_type": "webhook",
        "webhook_type": "generic",
        "default_methods": ["POST"],
    },
]


def get_trigger_catalog() -> list[dict[str, Any]]:
    """Return the full trigger catalog with events merged in."""
    catalog = []
    for entry in TRIGGER_CATALOG:
        item = {**entry}
        wt = entry.get("webhook_type")
        if wt and wt in CHANNEL_EVENTS:
            item["events"] = CHANNEL_EVENTS[wt]
        catalog.append(item)
    return catalog


def get_catalog_entry(trigger_id: str) -> dict[str, Any] | None:
    """Look up a catalog entry by ID."""
    for entry in TRIGGER_CATALOG:
        if entry["id"] == trigger_id:
            return entry
    return None


def get_catalog_entry_by_webhook_type(webhook_type: str) -> dict[str, Any] | None:
    """Look up a catalog entry by webhook_type."""
    for entry in TRIGGER_CATALOG:
        if entry.get("webhook_type") == webhook_type:
            return entry
    return None


# ── Channel event type registry ───────────────────────────────────
# Each channel maps to a list of supported event type strings.
# When a trigger has event_types configured, only matching events execute.
# Empty event_types means accept all events.

CHANNEL_EVENTS: dict[str, list[str]] = {
    "slack": [
        "message",
        "app_mention",
        "reaction_added",
        "reaction_removed",
        "channel_created",
        "channel_archive",
        "member_joined_channel",
        "member_left_channel",
        "file_shared",
        "file_created",
        "app_home_opened",
        "link_shared",
        "workflow_step_execute",
        "block_actions",
        "view_submission",
        "shortcut",
        "command",
    ],
    "github": [
        "push",
        "pull_request",
        "pull_request.opened",
        "pull_request.closed",
        "pull_request.merged",
        "pull_request.review_requested",
        "issues",
        "issues.opened",
        "issues.closed",
        "issues.labeled",
        "issue_comment",
        "issue_comment.created",
        "release",
        "release.published",
        "workflow_run",
        "workflow_run.completed",
        "check_run",
        "check_suite",
        "deployment",
        "deployment_status",
        "create",
        "delete",
        "fork",
        "star",
        "watch",
        "repository",
        "commit_comment",
        "status",
    ],
    "discord": [
        "MESSAGE_CREATE",
        "MESSAGE_UPDATE",
        "MESSAGE_DELETE",
        "MESSAGE_REACTION_ADD",
        "MESSAGE_REACTION_REMOVE",
        "GUILD_MEMBER_ADD",
        "GUILD_MEMBER_REMOVE",
        "GUILD_MEMBER_UPDATE",
        "CHANNEL_CREATE",
        "CHANNEL_UPDATE",
        "CHANNEL_DELETE",
        "INTERACTION_CREATE",
        "VOICE_STATE_UPDATE",
        "PRESENCE_UPDATE",
        "THREAD_CREATE",
        "THREAD_UPDATE",
    ],
    "telegram": [
        "message",
        "edited_message",
        "channel_post",
        "callback_query",
        "inline_query",
        "chosen_inline_result",
        "shipping_query",
        "pre_checkout_query",
        "poll",
        "poll_answer",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
    ],
    "linear": [
        "Issue",
        "Comment",
        "Project",
        "Cycle",
        "IssueLabel",
        "Reaction",
    ],
    "stripe": [
        "payment_intent.succeeded",
        "payment_intent.failed",
        "charge.succeeded",
        "charge.failed",
        "customer.created",
        "customer.updated",
        "invoice.paid",
        "invoice.payment_failed",
        "subscription.created",
        "subscription.updated",
        "subscription.deleted",
        "checkout.session.completed",
    ],
    "gmail": [
        "message_received",
        "label_changed",
    ],
    "teams": [
        "message",
        "conversationUpdate",
        "invoke",
        "messageReaction",
    ],
    "generic": [],
}


def get_channel_events(channel_type: str) -> list[str]:
    """Get supported event types for a channel. Returns empty list for unknown channels."""
    return CHANNEL_EVENTS.get(channel_type, [])


def is_valid_event(channel_type: str, event_type: str) -> bool:
    """Check if an event type is valid for a channel.

    Returns True if:
    - The channel has no defined events (accept anything)
    - The event_type matches exactly
    - The event_type matches a parent (e.g., 'push' matches 'push' for github)
    - The event_type is a sub-action of a defined parent (e.g., 'pull_request.opened' when 'pull_request' is defined)
    """
    events = CHANNEL_EVENTS.get(channel_type, [])
    if not events:
        return True
    if event_type in events:
        return True
    # Check if it's a sub-action of a defined event (e.g., "pull_request.opened" matches "pull_request")
    parent = event_type.split(".")[0]
    return parent in events
