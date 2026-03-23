# Context Window Management & Auto-Compaction

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add proactive context window management to agent execution workflows so conversations are automatically compacted before exceeding the model's context limit, preventing hard failures and maintaining reasoning quality.

**Architecture:** A `ContextWindowManager` is introduced alongside the existing `BudgetTracker` pattern. Before each LLM call, the manager estimates token usage against the model's `context_window` (already stored in `ModelSpec`). When usage crosses 75%, it compacts older messages via LLM summarization while preserving system prompt, recent messages, and complete tool_use/tool_result pairs. The `context_window` value is passed from `call_llm_activity` back to the workflow on the first LLM call.

**Tech Stack:** Python, Pydantic, Temporal workflows, tiktoken (for token estimation), existing LLM abstraction layer

**Research-backed design decisions (from LangChain, AutoGen, Anthropic SDK, OpenClaw, Google ADK, Manus):**
- **Proactive threshold at 75%** — CrewAI's reactive-only approach (compact on API error) causes degraded reasoning before failure. Anthropic SDK cookbook uses 75% (150k/200k). OpenClaw's 78% safeguard still hits orphan bugs.
- **Head-and-tail preservation** — AutoGen's `HeadAndTailChatCompletionContext` pattern: keep system prompt + initial task (head) and recent N messages (tail), summarize the middle.
- **Tool pair atomicity** — OpenClaw issues #7527, #3462 show orphaned `tool_result` blocks cause Anthropic API 400 errors. We must validate tool_use/tool_result pairs survive compaction intact.
- **LLM-based summarization** — LangGraph `SummarizationMiddleware`, Google ADK `LlmEventSummarizer`, and Anthropic `compact_20260112` all use LLM summarization over simple truncation. Truncation loses critical context; summarization preserves intent.
- **Token estimation with tiktoken** — Anthropic recommends server-side counting, but tiktoken `cl100k_base` gives ~5-10% approximation for Claude. Good enough for threshold decisions; we overestimate slightly for safety.
- **KV-cache awareness** — Per Manus engineering, keeping system prompt and early messages stable maximizes KV-cache hit rate. Our compaction replaces middle messages only, preserving the prefix.

---

## Chunk 1: Token Estimation & Context Window Tracking

### Task 1: Add context window constants and token estimation utility

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/workflows/constants.py`
- Create: `agentarea-platform/libs/execution/agentarea_execution/workflows/context_manager.py`
- Test: `agentarea-platform/libs/execution/tests/unit/test_context_manager.py`

- [ ] **Step 1: Write the failing test for token estimation**

```python
# agentarea-platform/libs/execution/tests/unit/test_context_manager.py
"""Tests for context window management."""

import pytest

from agentarea_execution.workflows.context_manager import (
    ContextWindowManager,
    estimate_tokens,
    validate_tool_pairs,
)
from agentarea_execution.workflows.models import Message


class TestEstimateTokens:
    """Test token estimation."""

    def test_estimate_tokens_simple_string(self):
        """Token count should be roughly chars/4 with overhead."""
        result = estimate_tokens("Hello, world!")
        # ~3-4 tokens for this string
        assert 2 <= result <= 10

    def test_estimate_tokens_empty_string(self):
        result = estimate_tokens("")
        assert result == 0

    def test_estimate_tokens_message_list(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        result = estimate_tokens_for_messages(messages)
        # Each message has ~4 token overhead + content tokens
        assert result > 0

    def test_estimate_tokens_with_tool_calls(self):
        messages = [
            {"role": "assistant", "content": "Let me help.", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q": "test"}'}}
            ]},
            {"role": "tool", "content": "Result data here", "tool_call_id": "call_1"},
        ]
        result = estimate_tokens_for_messages(messages)
        assert result > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agentarea-platform && python -m pytest libs/execution/tests/unit/test_context_manager.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Add constants for context window management**

```python
# Add to agentarea-platform/libs/execution/agentarea_execution/workflows/constants.py

# Context window management
CONTEXT_COMPACT_THRESHOLD: Final[float] = 0.75  # Compact at 75% of context window
CONTEXT_WARNING_THRESHOLD: Final[float] = 0.60  # Warn at 60%
CONTEXT_RESERVE_FOR_OUTPUT: Final[float] = 0.15  # Reserve 15% for model output
MIN_RECENT_MESSAGES_TO_KEEP: Final[int] = 6  # Always keep last 6 messages (3 turns)
TOKENS_PER_MESSAGE_OVERHEAD: Final[int] = 4  # ~4 tokens overhead per message
DEFAULT_CONTEXT_WINDOW: Final[int] = 128000  # Fallback if not set on model
```

- [ ] **Step 4: Implement token estimation and ContextWindowManager**

```python
# agentarea-platform/libs/execution/agentarea_execution/workflows/context_manager.py
"""Context window management for agent execution workflows.

Provides token estimation, context tracking, and auto-compaction to prevent
context window overflow during multi-turn agent executions.

Design informed by:
- Anthropic SDK compact_20260112 strategy (threshold-based proactive compaction)
- AutoGen HeadAndTailChatCompletionContext (preserve head + tail, summarize middle)
- OpenClaw tool pair validation (prevent orphaned tool_result blocks)
- Manus KV-cache optimization (keep prefix stable)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .constants import (
    CONTEXT_COMPACT_THRESHOLD,
    CONTEXT_RESERVE_FOR_OUTPUT,
    CONTEXT_WARNING_THRESHOLD,
    DEFAULT_CONTEXT_WINDOW,
    MIN_RECENT_MESSAGES_TO_KEEP,
    TOKENS_PER_MESSAGE_OVERHEAD,
)
from .models import Message

logger = logging.getLogger(__name__)

# Try to use tiktoken for better estimates, fall back to char-based
try:
    import tiktoken

    _encoding = tiktoken.get_encoding("cl100k_base")
    _HAS_TIKTOKEN = True
except ImportError:
    _encoding = None
    _HAS_TIKTOKEN = False


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Uses tiktoken cl100k_base if available (~5-10% error for Claude models),
    otherwise falls back to chars/3.5 (conservative overestimate).
    """
    if not text:
        return 0
    if _HAS_TIKTOKEN and _encoding is not None:
        return len(_encoding.encode(text))
    # Conservative fallback: ~3.5 chars per token, rounded up
    return max(1, int(len(text) / 3.5) + 1)


def estimate_tokens_for_messages(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of message dicts.

    Accounts for per-message overhead and tool call serialization.
    """
    total = 0
    for msg in messages:
        total += TOKENS_PER_MESSAGE_OVERHEAD  # role, separators
        content = msg.get("content", "")
        if content:
            total += estimate_tokens(content)
        # Tool calls add tokens for the JSON structure
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            total += estimate_tokens(json.dumps(tool_calls))
        # tool_call_id and name add small overhead
        if msg.get("tool_call_id"):
            total += estimate_tokens(msg["tool_call_id"])
        if msg.get("name"):
            total += estimate_tokens(msg["name"])
    return total


def validate_tool_pairs(messages: list[dict[str, Any]]) -> bool:
    """Validate that all tool_use/tool_result pairs are complete.

    Returns True if no orphaned tool_results exist (every tool_result has
    a matching tool_use in a preceding assistant message).

    This prevents Anthropic API 400 errors from orphaned tool_result blocks
    (ref: OpenClaw issues #7527, #3462).
    """
    # Collect all tool_use IDs from assistant messages
    tool_use_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict):
                    tc_id = tc.get("id")
                    if tc_id:
                        tool_use_ids.add(tc_id)

    # Check all tool messages reference a known tool_use
    for msg in messages:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id and tc_id not in tool_use_ids:
                return False
    return True


def find_compaction_boundary(
    messages: list[dict[str, Any]],
    keep_recent: int = MIN_RECENT_MESSAGES_TO_KEEP,
) -> int:
    """Find the safe boundary index for compaction.

    Returns the index that splits messages into [compactable | keep].
    The boundary respects:
    1. Always keep the first message (system prompt)
    2. Always keep the last `keep_recent` messages
    3. Never split a tool_use/tool_result pair

    Returns 0 if there's nothing safe to compact.
    """
    if len(messages) <= keep_recent + 1:
        # Not enough messages to compact (system + recent)
        return 0

    # Candidate boundary: everything except system prompt and recent messages
    candidate = len(messages) - keep_recent

    # Walk backward from candidate to find a safe split point
    # Safe = not in the middle of a tool call chain
    for i in range(candidate, 0, -1):
        msg = messages[i]
        # Don't split right before a tool result (would orphan it)
        if msg.get("role") == "tool":
            continue
        # Don't split right after an assistant message with tool_calls
        # (the tool results follow it)
        if i > 0:
            prev = messages[i - 1]
            if prev.get("role") == "assistant" and prev.get("tool_calls"):
                continue
        # This is a safe boundary
        return i

    return 0


class ContextWindowManager:
    """Manages context window usage and triggers compaction.

    Mirrors the BudgetTracker pattern for consistency.

    Usage:
        manager = ContextWindowManager(context_window=200000)
        manager.update_usage(prompt_tokens=150000)
        if manager.needs_compaction():
            # compact messages
    """

    def __init__(self, context_window: int | None = None):
        self.context_window = context_window or DEFAULT_CONTEXT_WINDOW
        self.compact_threshold = CONTEXT_COMPACT_THRESHOLD
        self.warning_threshold = CONTEXT_WARNING_THRESHOLD
        self.output_reserve = CONTEXT_RESERVE_FOR_OUTPUT
        self._last_prompt_tokens = 0
        self._warning_sent = False
        self._compaction_count = 0
        # Effective limit = context_window minus output reserve
        self._effective_limit = int(self.context_window * (1.0 - self.output_reserve))

    def update_usage(self, prompt_tokens: int) -> None:
        """Update with actual prompt token count from LLM response."""
        self._last_prompt_tokens = prompt_tokens

    def estimate_usage(self, messages: list[dict[str, Any]]) -> int:
        """Estimate token count for a message list."""
        return estimate_tokens_for_messages(messages)

    def get_usage_ratio(self) -> float:
        """Get current usage as ratio of effective limit."""
        if self._effective_limit <= 0:
            return 0.0
        return self._last_prompt_tokens / self._effective_limit

    def needs_compaction(self) -> bool:
        """Check if compaction should be triggered."""
        return self.get_usage_ratio() >= self.compact_threshold

    def should_warn(self) -> bool:
        """Check if a context warning should be sent."""
        return (
            self.get_usage_ratio() >= self.warning_threshold
            and not self._warning_sent
        )

    def mark_warning_sent(self) -> None:
        """Mark that warning has been sent."""
        self._warning_sent = True

    def mark_compacted(self) -> None:
        """Record that a compaction occurred."""
        self._compaction_count += 1

    @property
    def compaction_count(self) -> int:
        return self._compaction_count

    def get_status(self) -> dict[str, Any]:
        """Get current context window status."""
        return {
            "context_window": self.context_window,
            "effective_limit": self._effective_limit,
            "last_prompt_tokens": self._last_prompt_tokens,
            "usage_ratio": round(self.get_usage_ratio(), 3),
            "needs_compaction": self.needs_compaction(),
            "compaction_count": self._compaction_count,
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agentarea-platform && python -m pytest libs/execution/tests/unit/test_context_manager.py -v`
Expected: PASS

- [ ] **Step 6: Write additional tests for validate_tool_pairs and find_compaction_boundary**

```python
# Add to test_context_manager.py

from agentarea_execution.workflows.context_manager import (
    estimate_tokens_for_messages,
    find_compaction_boundary,
    validate_tool_pairs,
)


class TestValidateToolPairs:
    """Test tool pair validation (prevents orphaned tool_result blocks)."""

    def test_valid_pairs(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Search for X"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "Found X", "tool_call_id": "call_1"},
        ]
        assert validate_tool_pairs(messages) is True

    def test_orphaned_tool_result(self):
        """Orphaned tool_result should fail validation."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "tool", "content": "Found X", "tool_call_id": "call_missing"},
        ]
        assert validate_tool_pairs(messages) is False

    def test_no_tool_calls(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        assert validate_tool_pairs(messages) is True


class TestFindCompactionBoundary:
    """Test safe compaction boundary finding."""

    def test_too_few_messages(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        assert find_compaction_boundary(messages, keep_recent=6) == 0

    def test_does_not_split_tool_pair(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do stuff"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "more"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "result", "tool_call_id": "c1"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "welcome"},
        ]
        boundary = find_compaction_boundary(messages, keep_recent=4)
        # Should not land on index 5 (tool) or leave tool_calls orphaned
        assert boundary > 0
        # Validate the split produces valid tool pairs on both sides
        kept = messages[boundary:]
        assert validate_tool_pairs(kept)


class TestContextWindowManager:
    """Test ContextWindowManager."""

    def test_needs_compaction_under_threshold(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(prompt_tokens=50000)
        assert mgr.needs_compaction() is False

    def test_needs_compaction_over_threshold(self):
        mgr = ContextWindowManager(context_window=100000)
        # effective limit = 85000 (100k * 0.85), threshold at 75% = 63750
        mgr.update_usage(prompt_tokens=70000)
        assert mgr.needs_compaction() is True

    def test_warning_sent_once(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(prompt_tokens=55000)
        assert mgr.should_warn() is True
        mgr.mark_warning_sent()
        assert mgr.should_warn() is False

    def test_get_status(self):
        mgr = ContextWindowManager(context_window=200000)
        mgr.update_usage(prompt_tokens=100000)
        status = mgr.get_status()
        assert status["context_window"] == 200000
        assert status["last_prompt_tokens"] == 100000
        assert "usage_ratio" in status
```

- [ ] **Step 7: Run all tests**

Run: `cd agentarea-platform && python -m pytest libs/execution/tests/unit/test_context_manager.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add agentarea-platform/libs/execution/agentarea_execution/workflows/constants.py \
       agentarea-platform/libs/execution/agentarea_execution/workflows/context_manager.py \
       agentarea-platform/libs/execution/tests/unit/test_context_manager.py
git commit -m "feat: add context window manager with token estimation and tool pair validation"
```

---

### Task 2: Pass context_window from ModelSpec through to the workflow

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/models.py` (add `context_window` to `AgentConfigResult` and `LLMCallResult`)
- Modify: `agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py` (return `context_window` from activity)
- Modify: `agentarea-platform/libs/execution/agentarea_execution/workflows/models.py` (add `context_window` to `AgentExecutionState`)

- [ ] **Step 1: Add `context_window` to AgentConfigResult**

In `agentarea-platform/libs/execution/agentarea_execution/models.py`, add to `AgentConfigResult`:

```python
class AgentConfigResult(BaseModel):
    """Agent configuration result."""

    id: str
    name: str
    description: str
    instruction: str
    model_id: str
    context_window: int = 128000  # NEW: from ModelSpec
    tools: list[dict[str, Any]] = Field(default_factory=list)
    events_config: dict[str, Any] = Field(default_factory=dict)
    planning: bool = False
    execution_context: dict[str, Any] | None = None
    step_type: str | None = None
    skills: list[SkillInfo] = Field(default_factory=list)
```

- [ ] **Step 2: Add `context_window` to `LLMCallResult`**

In `agentarea-platform/libs/execution/agentarea_execution/models.py`, add to `LLMCallResult`:

```python
class LLMCallResult(BaseModel):
    """LLM call result."""

    role: str = "assistant"
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    cost: float = 0.0
    usage: LLMUsage | None = None
    context_window: int | None = None  # NEW: returned on first call
```

- [ ] **Step 3: Return `context_window` from `build_agent_config_activity`**

In `agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py`, modify `build_agent_config_activity` to fetch and return context_window:

After the agent is fetched (around line 89), add model spec lookup:

```python
            # Fetch model context window from ModelSpec
            model_id_str = request.override_model or agent.model_id
            context_window = 128000  # default fallback
            if model_id_str:
                try:
                    model_instance_service = await ctx.get_model_instance_service()
                    model_instance = await model_instance_service.get(UUID(model_id_str))
                    if model_instance and model_instance.model_spec:
                        context_window = model_instance.model_spec.context_window
                except Exception as e:
                    logger.warning(f"Could not fetch context_window for model {model_id_str}: {e}")
```

Then include it in the return:

```python
            return AgentConfigResult(
                # ... existing fields ...
                context_window=context_window,
            )
```

- [ ] **Step 4: Add `context_window` to `AgentExecutionState`**

In `agentarea-platform/libs/execution/agentarea_execution/workflows/models.py`:

```python
class AgentExecutionState(BaseModel):
    """Simplified execution state with direct attribute access."""
    # ... existing fields ...
    context_window: int = 128000  # NEW: populated from AgentConfigResult
```

- [ ] **Step 5: Store `context_window` in workflow state during initialization**

In `agentarea-platform/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py`, in `_initialize_agent_config()` after line 182:

```python
        # Store context window in state for context management
        self.state.context_window = self.state.agent_config.get("context_window", 128000)
```

- [ ] **Step 6: Commit**

```bash
git add agentarea-platform/libs/execution/agentarea_execution/models.py \
       agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py \
       agentarea-platform/libs/execution/agentarea_execution/workflows/models.py \
       agentarea-platform/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py
git commit -m "feat: pass context_window from ModelSpec through to workflow state"
```

---

## Chunk 2: Compaction Activity & Workflow Integration

### Task 3: Create the summarize_for_compaction activity

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/models.py` (add request/result models)
- Modify: `agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py` (add activity)
- Modify: `agentarea-platform/libs/execution/agentarea_execution/workflows/constants.py` (add activity name)

- [ ] **Step 1: Add compaction request/result models**

In `agentarea-platform/libs/execution/agentarea_execution/models.py`, add:

```python
class CompactMessagesRequest(BaseModel):
    """Request to compact/summarize older messages."""

    messages_to_compact: list[dict[str, Any]]
    model_id: str
    workspace_id: str
    user_context_data: dict[str, Any] | None = None


class CompactMessagesResult(BaseModel):
    """Result of message compaction."""

    summary: str
    original_message_count: int
    estimated_tokens_saved: int
```

- [ ] **Step 2: Add activity name constant**

In `constants.py`, add to `Activities`:

```python
    COMPACT_MESSAGES: Final[str] = "compact_messages_activity"
```

And add event type:

```python
    CONTEXT_COMPACTED: Final[str] = "ContextCompacted"
    CONTEXT_WARNING: Final[str] = "ContextWarning"
```

- [ ] **Step 3: Implement the compaction activity**

In `agent_execution_activities.py`, add the activity inside `make_agent_activities`:

```python
    @activity.defn
    async def compact_messages_activity(
        request: CompactMessagesRequest,
    ) -> CompactMessagesResult:
        """Summarize older messages to reduce context window usage.

        Uses the same model as the agent to generate a concise summary
        of older conversation history, preserving key decisions, tool
        results, and reasoning.
        """
        try:
            model_uuid = UUID(request.model_id)

            if request.workspace_id:
                user_context = create_system_context(request.workspace_id)
            elif request.user_context_data:
                user_context = create_user_context(request.user_context_data)
            else:
                raise ValueError("Either workspace_id or user_context_data must be provided")

            async with ActivityContext(container, user_context) as ctx:
                model_instance_service = await ctx.get_model_instance_service()
                model_instance = await model_instance_service.get(model_uuid)
                if not model_instance:
                    raise ValueError(f"Model instance {request.model_id} not found")

                provider_type = model_instance.provider_config.provider_spec.provider_type
                model_name = model_instance.model_spec.model_name
                endpoint_url = getattr(model_instance.model_spec, "endpoint_url", None)

                api_key = None
                api_key_secret_name = getattr(model_instance.provider_config, "api_key", None)
                if api_key_secret_name:
                    from agentarea_common.config import get_database
                    secret_session = get_database().async_session_factory()
                    try:
                        secret_manager = dependencies.secret_manager_factory.create(
                            session=secret_session, user_context=user_context
                        )
                        api_key = await secret_manager.get_secret(api_key_secret_name)
                    finally:
                        await secret_session.close()

            docker_host = os.environ.get("LLM_DOCKER_HOST")
            if docker_host and provider_type == "ollama_chat":
                endpoint_url = f"http://{docker_host}:11434"

            llm_model = LLMModel(
                provider_type=provider_type,
                model_name=model_name,
                api_key=api_key,
                endpoint_url=endpoint_url,
            )

            # Build compaction prompt
            conversation_text = ""
            for msg in request.messages_to_compact:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if msg.get("tool_calls"):
                    tool_names = [
                        tc.get("function", {}).get("name", "?")
                        for tc in msg["tool_calls"]
                        if isinstance(tc, dict)
                    ]
                    content += f" [Called tools: {', '.join(tool_names)}]"
                if msg.get("name"):
                    role = f"tool({msg['name']})"
                conversation_text += f"[{role}]: {content}\n"

            compaction_prompt = (
                "Summarize the following conversation history concisely. Preserve:\n"
                "1. The original task/goal\n"
                "2. Key decisions made and reasoning\n"
                "3. Important tool results and data obtained\n"
                "4. Current state of progress\n"
                "5. Any errors encountered and how they were handled\n\n"
                "Be concise but complete. Use bullet points for key facts.\n\n"
                f"Conversation to summarize:\n{conversation_text}"
            )

            summary_request = LLMRequest(
                messages=[
                    {"role": "system", "content": "You are a conversation summarizer. Create concise, factual summaries that preserve all important information for continuing the task."},
                    {"role": "user", "content": compaction_prompt},
                ],
                max_tokens=2000,
            )

            complete_content = ""
            async for chunk in llm_model.ainvoke_stream(summary_request):
                if chunk.content:
                    complete_content += chunk.content

            original_tokens = sum(
                len(msg.get("content", "")) // 4
                for msg in request.messages_to_compact
            )
            summary_tokens = len(complete_content) // 4

            return CompactMessagesResult(
                summary=complete_content,
                original_message_count=len(request.messages_to_compact),
                estimated_tokens_saved=max(0, original_tokens - summary_tokens),
            )

        except Exception as e:
            logger.error(f"Message compaction failed: {e}")
            # On failure, return a basic concatenation as fallback
            fallback = "Previous conversation summary (compaction failed):\n"
            for msg in request.messages_to_compact[-5:]:
                role = msg.get("role", "?")
                content = msg.get("content", "")[:200]
                fallback += f"- [{role}]: {content}\n"

            return CompactMessagesResult(
                summary=fallback,
                original_message_count=len(request.messages_to_compact),
                estimated_tokens_saved=0,
            )
```

- [ ] **Step 4: Register the activity in the return list**

Add `compact_messages_activity` to the returned list at the end of `make_agent_activities`:

```python
    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        create_execution_plan_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
        resolve_skill_file_activity,
        compact_messages_activity,  # NEW
    ]
```

- [ ] **Step 5: Import new models**

Add `CompactMessagesRequest` and `CompactMessagesResult` to the imports at top of `agent_execution_activities.py`:

```python
from ..models import (
    # ... existing imports ...
    CompactMessagesRequest,
    CompactMessagesResult,
)
```

- [ ] **Step 6: Commit**

```bash
git add agentarea-platform/libs/execution/agentarea_execution/models.py \
       agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py \
       agentarea-platform/libs/execution/agentarea_execution/workflows/constants.py
git commit -m "feat: add compact_messages_activity for LLM-based conversation summarization"
```

---

### Task 4: Integrate ContextWindowManager into the execution workflow

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py`

This is the critical integration task. The ContextWindowManager is initialized during workflow startup and checked before each LLM call. When compaction is needed, the workflow calls the compaction activity and replaces old messages with the summary.

- [ ] **Step 1: Add imports to workflow**

At the top of `agent_execution_workflow.py`, inside the `workflow.unsafe.imports_passed_through()` block:

```python
with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from .helpers import (
        BudgetTracker,
        EventManager,
        MessageBuilder,
        StateValidator,
        ToolCallExtractor,
    )
    from .context_manager import (  # NEW
        ContextWindowManager,
        find_compaction_boundary,
        validate_tool_pairs,
    )
    from .models import (
        AgentExecutionState,
        AgentGoal,
        Message,
        ToolCall,
    )
```

Add to the external imports:

```python
from ..models import (
    # ... existing imports ...
    CompactMessagesRequest,
    CompactMessagesResult,
)
```

- [ ] **Step 2: Initialize ContextWindowManager in `_initialize_workflow`**

Add after `self.budget_tracker = BudgetTracker(self.state.budget_usd)` (line 138):

```python
        self.context_manager: ContextWindowManager | None = None
```

Then in `_initialize_agent_config`, after storing `context_window` in state:

```python
        # Initialize context window manager
        self.context_manager = ContextWindowManager(self.state.context_window)
```

- [ ] **Step 3: Add `_compact_context_if_needed` method**

Add this method to `AgentExecutionWorkflow`:

```python
    async def _compact_context_if_needed(self) -> bool:
        """Check context usage and compact if threshold exceeded.

        Uses the head-and-tail strategy:
        1. Keep system prompt (head)
        2. Summarize middle messages via LLM
        3. Keep recent messages (tail)
        4. Validate tool pairs aren't broken

        Returns True if compaction was performed.
        """
        if not self.context_manager:
            return False

        if not self.context_manager.needs_compaction():
            return False

        workflow.logger.info(
            f"Context compaction triggered at {self.context_manager.get_usage_ratio():.1%} usage"
        )

        # Convert messages to dict for boundary finding
        messages_dict = [
            MessageBuilder.normalize_message_dict({
                "role": msg.role,
                "content": msg.content,
                "tool_call_id": msg.tool_call_id,
                "name": msg.name,
                "tool_calls": msg.tool_calls,
            })
            for msg in self.state.messages
        ]

        # Find safe compaction boundary
        boundary = find_compaction_boundary(messages_dict)
        if boundary <= 1:
            workflow.logger.warning("No safe compaction boundary found, skipping")
            return False

        # Messages to compact: everything between system prompt and boundary
        # Keep system prompt (index 0), compact indices 1..boundary-1
        messages_to_compact = messages_dict[1:boundary]
        if not messages_to_compact:
            return False

        # Call compaction activity
        try:
            compact_request = CompactMessagesRequest(
                messages_to_compact=messages_to_compact,
                model_id=self.state.agent_config.get("model_id"),
                workspace_id=self.state.workspace_id,
                user_context_data=self.state.user_context_data,
            )

            result: CompactMessagesResult = await workflow.execute_activity(
                Activities.COMPACT_MESSAGES,
                args=[compact_request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Rebuild message list: system prompt + summary + kept recent messages
            system_msg = self.state.messages[0]
            recent_messages = list(self.state.messages[boundary:])

            summary_msg = Message(
                role="user",
                content=f"[Previous conversation summary]\n{result.summary}",
            )

            self.state.messages = [system_msg, summary_msg] + recent_messages

            # Validate tool pairs in new message list
            new_messages_dict = [
                MessageBuilder.normalize_message_dict({
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                    "tool_calls": msg.tool_calls,
                })
                for msg in self.state.messages
            ]
            if not validate_tool_pairs(new_messages_dict):
                workflow.logger.error("Tool pair validation failed after compaction!")
                # Repair: drop orphaned tool results
                repaired = []
                tool_use_ids: set[str] = set()
                for msg in self.state.messages:
                    if msg.role == "assistant" and msg.tool_calls:
                        for tc in msg.tool_calls:
                            if isinstance(tc, dict) and tc.get("id"):
                                tool_use_ids.add(tc["id"])
                    if msg.role == "tool" and msg.tool_call_id not in tool_use_ids:
                        workflow.logger.warning(
                            f"Dropping orphaned tool_result: {msg.tool_call_id}"
                        )
                        continue
                    repaired.append(msg)
                self.state.messages = repaired

            self.context_manager.mark_compacted()

            # Publish compaction event
            self.event_manager.add_event(
                EventTypes.CONTEXT_COMPACTED,
                {
                    "iteration": self.state.current_iteration,
                    "messages_compacted": result.original_message_count,
                    "tokens_saved": result.estimated_tokens_saved,
                    "compaction_number": self.context_manager.compaction_count,
                    "messages_remaining": len(self.state.messages),
                },
            )
            await self._publish_events_immediately()

            workflow.logger.info(
                f"Compacted {result.original_message_count} messages, "
                f"~{result.estimated_tokens_saved} tokens saved, "
                f"{len(self.state.messages)} messages remaining"
            )
            return True

        except Exception as e:
            workflow.logger.error(f"Context compaction failed: {e}")
            # Don't fail the workflow - just continue with full context
            return False
```

- [ ] **Step 4: Update `_call_llm` to track context usage and trigger compaction**

In `_call_llm()`, after extracting usage (around line 483-487), add context tracking:

```python
            # Update context window manager with actual token usage
            if self.context_manager and usage_payload:
                prompt_tokens = usage_payload.get("prompt_tokens", 0)
                if prompt_tokens > 0:
                    self.context_manager.update_usage(prompt_tokens)
```

- [ ] **Step 5: Add compaction check before each LLM call in `_execute_traditional_iteration`**

In `_execute_traditional_iteration()`, right before `llm_response = await self._call_llm()` (line 398), add:

```python
            # Check context window and compact if needed
            if self.context_manager and self.state.current_iteration > 1:
                # Estimate current usage from messages
                messages_dict_est = [
                    {"role": msg.role, "content": msg.content or ""}
                    for msg in self.state.messages
                ]
                estimated = self.context_manager.estimate_usage(messages_dict_est)
                self.context_manager.update_usage(estimated)

                if self.context_manager.needs_compaction():
                    await self._compact_context_if_needed()
                elif self.context_manager.should_warn():
                    self.event_manager.add_event(
                        EventTypes.CONTEXT_WARNING,
                        {
                            "iteration": self.state.current_iteration,
                            "usage_ratio": self.context_manager.get_usage_ratio(),
                            "message_count": len(self.state.messages),
                        },
                    )
                    await self._publish_events_immediately()
                    self.context_manager.mark_warning_sent()
```

- [ ] **Step 6: Add context info to `get_current_state` query**

In `get_current_state()`, add:

```python
            "context": self.context_manager.get_status() if self.context_manager else None,
```

- [ ] **Step 7: Commit**

```bash
git add agentarea-platform/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py
git commit -m "feat: integrate context window management into agent execution loop"
```

---

### Task 5: Register the compaction activity in the Temporal worker

**Files:**
- Find and modify the worker registration file that calls `make_agent_activities()` and registers activities with the Temporal worker

- [ ] **Step 1: Find the worker registration**

Search for where `make_agent_activities` is called and activities are registered with the Temporal worker. The new `compact_messages_activity` is already included in the returned list from `make_agent_activities()`, so it should be auto-registered. Verify this is the case.

Run: `grep -r "make_agent_activities" agentarea-platform/`

- [ ] **Step 2: Verify the activity is auto-registered**

Since `make_agent_activities()` returns a list of all activities and the worker registers all of them, the new activity should be automatically included. Confirm by reading the worker setup code.

- [ ] **Step 3: Commit (if changes needed)**

---

### Task 6: Add tiktoken as an optional dependency

**Files:**
- Modify: `agentarea-platform/libs/execution/pyproject.toml` (add tiktoken as optional dep)

- [ ] **Step 1: Add tiktoken to dependencies**

Add `tiktoken` to the execution library's dependencies:

```toml
[project.optional-dependencies]
tokenizer = ["tiktoken>=0.7.0"]
```

Or add it as a regular dependency if token counting is critical:

```toml
dependencies = [
    # ... existing deps ...
    "tiktoken>=0.7.0",
]
```

- [ ] **Step 2: Commit**

```bash
git add agentarea-platform/libs/execution/pyproject.toml
git commit -m "feat: add tiktoken dependency for accurate token estimation"
```

---

## Chunk 3: Integration Tests & Event Handling

### Task 7: Write integration tests for the compaction flow

**Files:**
- Create: `agentarea-platform/libs/execution/tests/unit/test_context_compaction_flow.py`

- [ ] **Step 1: Write integration test for end-to-end compaction**

```python
# agentarea-platform/libs/execution/tests/unit/test_context_compaction_flow.py
"""Tests for context compaction integration with workflow."""

import pytest

from agentarea_execution.workflows.context_manager import (
    ContextWindowManager,
    estimate_tokens_for_messages,
    find_compaction_boundary,
    validate_tool_pairs,
)
from agentarea_execution.workflows.models import Message


def _make_conversation(num_turns: int, content_size: int = 500) -> list[dict]:
    """Generate a synthetic conversation with tool calls."""
    messages = [
        {"role": "system", "content": "You are a helpful agent."},
        {"role": "user", "content": "Please help me with a complex task."},
    ]
    for i in range(num_turns):
        # Assistant with tool call
        messages.append({
            "role": "assistant",
            "content": f"Step {i}: I'll use a tool. " + "x" * content_size,
            "tool_calls": [{
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"tool_{i}", "arguments": '{"key": "value"}'},
            }],
        })
        # Tool result
        messages.append({
            "role": "tool",
            "content": f"Result for step {i}: " + "data " * (content_size // 5),
            "tool_call_id": f"call_{i}",
            "name": f"tool_{i}",
        })
    # Final assistant response
    messages.append({"role": "assistant", "content": "I've completed the analysis."})
    return messages


class TestCompactionFlow:
    """Test the full compaction flow."""

    def test_large_conversation_triggers_compaction(self):
        """A long conversation should trigger compaction."""
        messages = _make_conversation(20, content_size=1000)
        mgr = ContextWindowManager(context_window=50000)
        tokens = mgr.estimate_usage(messages)
        mgr.update_usage(tokens)
        assert mgr.needs_compaction() is True

    def test_compaction_boundary_preserves_recent(self):
        """Compaction should keep recent messages intact."""
        messages = _make_conversation(10)
        boundary = find_compaction_boundary(messages, keep_recent=6)
        assert boundary > 0
        kept = messages[boundary:]
        assert len(kept) >= 6

    def test_compaction_boundary_preserves_tool_pairs(self):
        """Tool call/result pairs should not be split."""
        messages = _make_conversation(10)
        boundary = find_compaction_boundary(messages, keep_recent=6)
        kept = messages[boundary:]
        assert validate_tool_pairs(kept)

    def test_small_conversation_no_compaction(self):
        """Short conversations should not need compaction."""
        messages = _make_conversation(2, content_size=100)
        mgr = ContextWindowManager(context_window=200000)
        tokens = mgr.estimate_usage(messages)
        mgr.update_usage(tokens)
        assert mgr.needs_compaction() is False

    def test_multiple_compactions(self):
        """Manager should track multiple compaction rounds."""
        mgr = ContextWindowManager(context_window=50000)
        mgr.update_usage(40000)
        assert mgr.needs_compaction() is True
        mgr.mark_compacted()
        assert mgr.compaction_count == 1

        # Simulate post-compaction state
        mgr.update_usage(10000)
        assert mgr.needs_compaction() is False

        # Context grows again
        mgr.update_usage(40000)
        assert mgr.needs_compaction() is True
        mgr.mark_compacted()
        assert mgr.compaction_count == 2

    def test_orphan_repair_scenario(self):
        """Simulate what happens when compaction creates orphans."""
        # This simulates the OpenClaw #7527 bug scenario
        messages = [
            {"role": "system", "content": "sys"},
            # After compaction, this tool_result has no matching tool_use
            {"role": "tool", "content": "orphaned result", "tool_call_id": "missing_call"},
            {"role": "assistant", "content": "continuing..."},
        ]
        assert validate_tool_pairs(messages) is False

        # Repair by filtering orphans
        tool_use_ids = set()
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict) and tc.get("id"):
                        tool_use_ids.add(tc["id"])

        repaired = [
            msg for msg in messages
            if not (msg.get("role") == "tool" and msg.get("tool_call_id") not in tool_use_ids)
        ]
        assert validate_tool_pairs(repaired) is True
        assert len(repaired) == 2  # system + assistant
```

- [ ] **Step 2: Run tests**

Run: `cd agentarea-platform && python -m pytest libs/execution/tests/unit/test_context_compaction_flow.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add agentarea-platform/libs/execution/tests/unit/test_context_compaction_flow.py
git commit -m "test: add integration tests for context compaction flow"
```

---

### Task 8: Handle context events in the frontend

**Files:**
- Find and modify the frontend event handling to display context compaction/warning events

- [ ] **Step 1: Find the SSE event handler in the frontend**

Search in `agentarea-webapp/src/` for where workflow events (like `BudgetWarning`, `IterationCompleted`) are handled and displayed.

- [ ] **Step 2: Add handling for `ContextWarning` and `ContextCompacted` events**

Add cases for the new event types alongside existing event handling (like `BudgetWarning`):

- `ContextWarning`: Display a warning indicator showing context usage percentage
- `ContextCompacted`: Display a brief notification that conversation was summarized

- [ ] **Step 3: Run frontend build to verify**

Run: `cd agentarea-webapp && npm run build`

- [ ] **Step 4: Commit**

```bash
git add agentarea-webapp/src/
git commit -m "feat: display context window warning and compaction events in UI"
```

---

## Summary of Changes

### New Files
| File | Purpose |
|------|---------|
| `workflows/context_manager.py` | Token estimation, ContextWindowManager, tool pair validation, compaction boundary logic |
| `tests/unit/test_context_manager.py` | Unit tests for context manager |
| `tests/unit/test_context_compaction_flow.py` | Integration tests for compaction flow |

### Modified Files
| File | Change |
|------|--------|
| `workflows/constants.py` | Add context window constants, event types, activity name |
| `workflows/models.py` | Add `context_window` to `AgentExecutionState` |
| `models.py` | Add `context_window` to `AgentConfigResult` and `LLMCallResult`; add `CompactMessagesRequest/Result` |
| `activities/agent_execution_activities.py` | Add `compact_messages_activity`; return `context_window` from config |
| `workflows/agent_execution_workflow.py` | Initialize `ContextWindowManager`; add `_compact_context_if_needed`; check before each LLM call |
| Frontend event handler | Display `ContextWarning`/`ContextCompacted` events |

### Architecture Decisions
| Decision | Rationale |
|----------|-----------|
| 75% compaction threshold | Cross-framework consensus; avoids "context rot" zone (>80%) while not being too aggressive |
| LLM-based summarization | Preserves reasoning intent better than truncation (LangGraph, Google ADK, Anthropic all use this) |
| Head-and-tail preservation | AutoGen pattern; keeps system prompt stable (KV-cache friendly per Manus) + recent context intact |
| Tool pair validation + repair | Prevents Anthropic API 400 from orphaned tool_results (OpenClaw bugs #7527, #3462) |
| tiktoken with fallback | Best available client-side estimation for Claude; graceful degradation to char-based |
| Activity-based compaction | Follows existing Temporal patterns; compaction runs outside workflow sandbox |
| Mirrors BudgetTracker pattern | Consistent codebase patterns; easy to understand alongside existing budget tracking |
