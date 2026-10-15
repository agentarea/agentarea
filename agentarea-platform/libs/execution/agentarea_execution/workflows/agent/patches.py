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
# A final answer that leaks (CJK, tool names, codes, stack traces, JSON, English
# in a Russian answer) gets one rewrite call when the policy's answer_check is on.
ANSWER_CHECK_REWRITE_PATCH = "answer-check-rewrite-v1"
# Stopping a run waits for the tool call it interrupted to stop, and records what
# that call returned and cost, flagged cancelled; before, the run abandoned it.
STOP_SETTLES_IN_FLIGHT_TOOL_PATCH = "stop-settles-in-flight-tool-v1"
# A cancelled or failed run answers its open tool calls and stores a resume
# snapshot, so a later message or a retry continues the conversation; before,
# only a completed run could be continued.
RESUME_AFTER_STOP_OR_FAILURE_PATCH = "resume-after-stop-or-failure-v1"
# With the answer check on, a text-only reply is checked before its
# llm.call.completed goes out, so the person never sees the unchecked text;
# before, the check ran at completion and its rewrite replaced the shown reply.
ANSWER_CHECK_BEFORE_REPLY_PATCH = "answer-check-before-reply-v1"
# A model call a stop interrupts is told to stop and waited for: what it cost,
# when the provider reported usage, is recorded flagged cancelled, and otherwise
# the call is recorded as cut off with its cost unknown.
STOP_SETTLES_MODEL_CALL_PATCH = "stop-settles-model-call-v1"
# A model call refused because a monthly cap on LLM spend was reached mid-run (the
# turn or compaction) ends the run as the start-of-run cap check does; before, the
# refusal failed the run as a model error.
SPEND_CAP_REACHED_STOPS_RUN_PATCH = "spend-cap-reached-stops-run-v1"
# Every turn.started is closed: a turn that ends early (failure, cancellation, a
# limit, a spend cap or a block) records turn.aborted with why; before, such a
# turn just had no closing event.
TURN_ABORTED_EVENT_PATCH = "turn-aborted-event-v1"
# A model call a stop cuts off before the provider replied ends as a cancelled
# llm.call.completed with its cost unknown; before, it was reported as
# llm.call.failed, so a cancelled run read as one that hit an error.
STOPPED_MODEL_CALL_IS_NOT_A_FAILURE_PATCH = "stopped-model-call-is-not-a-failure-v1"
# The run writes its task log through one record activity: the log rows, the
# task status, then its events, after each model call and tool result. Model
# calls and compaction read the window from the log (the system prompt, the
# latest compaction and what follows) instead of cursors the run carried, and
# write nothing; model changes and approvals are event rows. Before, the model
# call wrote the conversation and the status had its own activity.
TASK_LOG_RECORD_PATCH = "task-log-record-v1"
