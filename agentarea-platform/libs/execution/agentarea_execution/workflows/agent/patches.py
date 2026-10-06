"""Replay patch ids. Histories recorded before each change replay its old commands."""

GOVERNANCE_VERDICT_PATCH = "governance-verdict-to-hitl-v1"
THINKING_ONLY_REPLY_PATCH = "thinking-only-reply-is-empty-v1"
APPROVAL_RESPONSE_ONCE_PATCH = "approval-response-once-v1"
DELEGATION_ON_OWN_QUEUE_PATCH = "delegation-on-own-task-queue-v1"
MONTHLY_CAP_AT_START_PATCH = "monthly-cap-at-start"
INTERACTION_CONTRACT_PATCH = "channel-aware-interaction-v1"
LONG_RUN_LOOP_PATCH = "long-run-loop-checks-v1"
COMPACTION_BOUNDS_PAYLOAD_PATCH = "compaction-bounds-payload-v1"
CANCELLATION_PROPAGATES_PATCH = "cancellation-propagates-v1"
WAIT_TOOL_PATCH = "wait-tool-v1"
WEB_FETCH_SEEN_URL_PATCH = "web-fetch-seen-url-v1"
TOOL_CONFIG_ALIASES_PATCH = "tool-config-aliases-v1"
CONVERSATION_RESUME_SNAPSHOT_PATCH = "conversation-resume-snapshot-v1"
# A paid model call (turn or compaction) is persisted before the run limits it
# crossed stop the run; before, the limit raised first and the call was never billed.
PAID_CALL_PERSISTED_BEFORE_LIMITS_PATCH = "paid-call-persisted-before-limits-v1"
# A governance gate refusing the model call blocks the run with the gate's code
# through normal finalization; before, the run failed with a generic model error.
GOVERNANCE_DENIAL_BLOCKS_RUN_PATCH = "governance-denial-blocks-run-v1"
# The run's input is the first user message only, pinned in the window's head;
# before, the system prompt repeated it and compaction could summarize the message.
RUN_INPUT_IN_FIRST_MESSAGE_PATCH = "run-input-in-first-message-v1"
