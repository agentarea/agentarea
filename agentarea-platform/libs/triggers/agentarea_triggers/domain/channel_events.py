"""Channel event type registry.

Maps each webhook channel to its supported event types.
Used for event filtering on triggers and for the frontend event selector.
"""

# Channel event type registry
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
