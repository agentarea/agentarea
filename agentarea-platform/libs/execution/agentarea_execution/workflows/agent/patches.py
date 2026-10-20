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
# The run's events are rows of its task log, written by the record activity
# with the messages; the task's feed reads them there. Model changes and
# approvals are those event rows, not rows of their own. Before, events went
# to the record activity beside the rows and were stored elsewhere.
TASK_EVENTS_IN_LOG_PATCH = "task-events-in-log-v1"
# One continuation grant is applied at a time: while a grant persists its policy
# revision a second one is refused; before, concurrent grants all succeeded and
# a later one could lower the limit an earlier one raised.
SERIAL_CONTINUATION_GRANTS_PATCH = "serial-continuation-grants-v1"
# A follow-up still queued when the run ends (stopped, failed, or closing after
# its idle wait) is written to the log as the person's message, so the next run
# answers it; before, the queue was dropped with the run.
QUEUED_MESSAGES_KEPT_ON_CLOSE_PATCH = "queued-messages-kept-on-close-v1"
# A run that ends before its first turn wrote the system prompt and the request
# stores no resume snapshot, so the next run rebuilds and seeds them; before,
# its snapshot claimed a first turn and the next run skipped the seeding.
RESUME_SNAPSHOT_NEEDS_SEEDED_LOG_PATCH = "resume-snapshot-needs-seeded-log-v1"
# Stopping a run during compaction waits for the summary call and records it as
# a cancelled llm.call.completed with its cost; before, the paid call vanished.
STOP_SETTLES_COMPACTION_PATCH = "stop-settles-compaction-v1"
# A delegated child's task row carries its workflow id as execution_id, so the
# API can stop, pause and resume it; before, the row had none.
DELEGATION_CHILD_EXECUTION_ID_PATCH = "delegation-child-execution-id-v1"
# A stop resolves the escalations the run was waiting on as denied, so none
# stays pending on a run that will never act on it.
STOP_RESOLVES_ESCALATIONS_PATCH = "stop-resolves-escalations-v1"
# The monthly spend caps checked at the start of a run, at resume and after a
# continuation are read from the workspace's and agent's policies as they are now;
# before, a run used the caps frozen in its policy, so a cap lowered while it ran
# never stopped it.
CURRENT_SPEND_CAPS_PATCH = "current-spend-caps-v1"
# A run that hits a limit a workspace, agent or user policy already sets at its
# ceiling ends instead of waiting for a continuation grant no one can give;
# before, it waited the full continuation window.
CONTINUATION_WITHIN_POLICY_CEILING_PATCH = "continuation-within-policy-ceiling-v1"
# Stopping a run while a delegated agent works answers the delegation's call as
# stopped, records delegation.failed flagged cancelled and reserves the child's
# allocation in the parent's cost; before, the call read "Not executed" and the
# child's spend was missing from the parent.
DELEGATION_STOP_RECORDED_PATCH = "delegation-stop-recorded-v1"
# A compaction runs again only once the prompt grew by a tenth of the usable window
# since the first call after the last one; before, a context whose fixed part (system
# prompt, tool schemas, summary) sat above the threshold was compacted every turn,
# each a paid call that freed nothing.
COMPACTION_NEEDS_ROOM_PATCH = "compaction-needs-room-v1"
# A resume signal to a run that is not paused changes nothing and records no
# execution.resumed; before, every resume recorded one.
RESUME_ONLY_WHEN_PAUSED_PATCH = "resume-only-when-paused-v1"
# A paid model reply that takes the run past its run budget or token limit stays
# in the conversation, its tool calls answered as not executed; before, it was
# billed and published but missing from the task log.
PAID_REPLY_KEPT_AT_LIMIT_PATCH = "paid-reply-kept-at-limit-v1"
# A turn that completes the task stores the completed status with its
# turn.completed and task.completed rows, in one record; before, the status
# was stored first and the feed showed the completion seconds later.
COMPLETED_STATUS_WITH_TURN_EVENTS_PATCH = "completed-status-with-turn-events-v1"
# A model call refused at a monthly spend cap records no llm.call.failed; the
# turn's turn.aborted (spend_cap) says why it ended. Before, the refusal also read
# as "Failed to get a response from the AI model."
SPEND_CAP_REFUSAL_NOT_A_CALL_FAILURE_PATCH = "spend-cap-refusal-not-a-call-failure-v1"
# A tool call refused before it ran (a policy denial, a monthly cap, an oversized
# turn) records its tool.call before its tool.result; before, the result had no
# call.
REFUSED_TOOL_CALL_ANNOUNCED_PATCH = "refused-tool-call-announced-v1"
# Whether a completed turn waits for a follow-up, and for how long, is read from
# the task's session (continue, idle timeout); before, only a web chat waited,
# always 30 minutes, so a chat channel's next message found no task waiting.
SESSION_DECIDES_FOLLOW_UP_PATCH = "session-decides-follow-up-v1"
# A run that continues a closed conversation takes its place at the end of the
# log before its first record; before, its task.started was written at row 0,
# which the earlier run holds, and the run failed on the duplicate row.
RESUME_POSITION_BEFORE_FIRST_RECORD_PATCH = "resume-position-before-first-record-v1"
# A run whose task nothing marked running (booked for later, or a delegated
# agent's) marks it running when it starts; before, the task stayed
# "scheduled" or "submitted" until it ended, showed in the schedule while it
# ran and never got a started_at.
UNSTARTED_TASK_MARKED_RUNNING_PATCH = "unstarted-task-marked-running-v1"
# A delegated agent stopped on its own (its task cancelled, not the parent's)
# answers the delegation as stopped and the parent carries on; before, its
# cancellation read as the parent's own and stopped the parent too.
CHILD_STOP_IS_NOT_PARENT_STOP_PATCH = "child-stop-is-not-parent-stop-v1"
# Activating a skill reads its SKILL.md in an activity; before, the body rode in
# the config activity's result and activation used that copy.
SKILL_BODY_ON_ACTIVATION_PATCH = "skill-body-on-activation-v1"
