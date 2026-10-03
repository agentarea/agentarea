"""Long-running agent workflows on a real Temporal server.

A task that works for a day crosses dozens of continue-as-new boundaries,
compacts its conversation, and outlives transient outages of everything it
talks to. The dev server here runs with a low continue-as-new threshold, so a
few dozen iterations exercise the same boundaries a day-long run does.
"""

from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from agentarea_common.money import to_money
from agentarea_common.testing.temporal import temporal_download_dir
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    CompactMessagesRequest,
    CompactMessagesResult,
    ConversationWindow,
    DiscoverToolProvidersResult,
    LLMCallRequest,
    LLMCallResult,
    LLMUsage,
    MCPToolRequest,
    MCPToolResult,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    ToolProviderData,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.context_manager import (
    compactable_prefix,
    estimate_tokens_for_messages,
)
from temporalio import activity
from temporalio.client import Client, WorkflowFailureError, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# Temporal suggests continue-as-new at 4096 events in production; at 150 a run
# continues as new every two or three iterations.
_CONTINUE_AS_NEW_EVENTS = 150
_TEMPORAL_BLOB_LIMIT_BYTES = 2 * 1024 * 1024


def _tool(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Does one unit of work.",
            "parameters": {
                "type": "object",
                "properties": {"step": {"type": "integer"}},
                "required": ["step"],
            },
        },
    }


_TOOL = _tool("work_step")


@dataclass
class Scenario:
    """What the stubbed model and tools do, and what the workflow published."""

    iterations: int = 10
    conversation: bool = False
    context_window: int = 128_000
    context_strategy: str = "static"
    reply_content: str = ""
    tool_output: str = "ok"
    call_cost: str = "0.0001"
    compaction_cost: str = "0.0001"
    first_call_cost: str | None = None
    tools_per_turn: int = 1
    llm_failures: int = 0
    publish_failures_on_iteration: int | None = None
    publish_failures: int = 0
    llm_delay_seconds: float = 0.0
    tool_delay_seconds: float = 0.0
    dynamic_sources: bool = False
    hold_continue_as_new_publish: bool = False

    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    event_order: list[str] = field(default_factory=list)
    llm_requests: list[LLMCallRequest] = field(default_factory=list)
    llm_request_bytes: list[int] = field(default_factory=list)
    compactions: int = 0
    llm_attempts: collections.Counter = field(default_factory=collections.Counter)
    publish_attempts: collections.Counter = field(default_factory=collections.Counter)
    continue_as_new_publishing: asyncio.Event = field(default_factory=asyncio.Event)
    continue_as_new_released: asyncio.Event = field(default_factory=asyncio.Event)
    # The task's conversation log, as the activities keep it: seq -> message.
    log: dict[int, dict[str, Any]] = field(default_factory=dict)

    def write(self, window: ConversationWindow, pending: list[dict[str, Any]]) -> int:
        for offset, message in enumerate(pending):
            self.log[window.next_seq + offset] = message
        return window.next_seq + len(pending)

    def window_messages(
        self, window: ConversationWindow, end_seq: int
    ) -> tuple[list[int], list[int]]:
        head = list(window.head_seqs)
        tail = [
            seq
            for seq in sorted(self.log)
            if window.tail_start <= seq < end_seq and seq not in head
        ]
        return head, tail

    def published(self, event_type: str) -> list[dict[str, Any]]:
        return [
            self.events[event_id]
            for event_id in self.event_order
            if self.events[event_id]["event_type"] == event_type
        ]

    def user_messages_seen(self) -> set[str]:
        return {
            message.get("content") or ""
            for request in self.llm_requests
            for message in request.messages
            if message.get("role") == "user"
        }


def _source_to_activate(iteration: int, iterations: int, tools: list[dict[str, Any]]) -> str | None:
    """Workbench first; the archive only late in the run, after several rollovers."""
    offered = {(tool.get("function") or {}).get("name") for tool in tools}
    if "work_step" not in offered:
        return "workbench"
    if iteration >= iterations - 3 and "archive_step" not in offered:
        return "archive"
    return None


def _activities(scenario: Scenario) -> list[Any]:
    @activity.defn(name="build_agent_config_activity")
    async def build_config(request: AgentConfigRequest) -> dict[str, Any]:
        return {
            "id": str(request.agent_id),
            "name": "Long Runner",
            "model_id": "model-long-run",
            "description": "long run",
            "instruction": "Work until the job is done.",
            "tools_config": {"mcp_servers": []},
            "context_window": scenario.context_window,
            "context_strategy": scenario.context_strategy,
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
        return {"tools": [_TOOL], "context_strategy": scenario.context_strategy}

    @activity.defn(name="discover_tool_providers_activity")
    async def discover_providers(request: ToolDiscoveryRequest) -> DiscoverToolProvidersResult:
        return DiscoverToolProvidersResult(
            providers=[
                ToolProviderData(
                    name=source,
                    provider_type="code",
                    tool_names=[tool],
                    description=f"Tools of the {source}.",
                    tools=[_tool(tool)],
                )
                for source, tool in (("workbench", "work_step"), ("archive", "archive_step"))
            ]
        )

    @activity.defn(name="resolve_model_activity")
    async def resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
        return {
            "model_id": request.model_id,
            "provider_type": "openai",
            "model_name": "long-run-model",
            "api_key_secret": None,
            "endpoint_url": None,
            "context_window": scenario.context_window,
            "input_cost_per_token": "0.0000001",
            "output_cost_per_token": "0.0000002",
            "display_name": "Long Run",
            "provider_display_name": "Stub",
            "resolved_at": "2026-01-01T00:00:00+00:00",
        }

    @activity.defn(name="call_llm_activity")
    async def call_llm(request: LLMCallRequest) -> LLMCallResult:
        iteration = request.iteration or 0
        scenario.llm_attempts[iteration] += 1
        if scenario.llm_attempts[iteration] <= scenario.llm_failures:
            raise RuntimeError("503 upstream connect error")
        if scenario.llm_delay_seconds:
            await asyncio.sleep(scenario.llm_delay_seconds)
        scenario.llm_requests.append(request)
        scenario.llm_request_bytes.append(len(request.model_dump_json().encode()))
        cost = scenario.first_call_cost if iteration == 1 and scenario.first_call_cost else None
        cost = cost or scenario.call_cost
        context = request.messages
        if request.conversation is not None:
            end_seq = scenario.write(request.conversation, request.messages)
            head, tail = scenario.window_messages(request.conversation, end_seq)
            context = [scenario.log[seq] for seq in (*head, *tail)]
        prompt_tokens = max(1, sum(len(m.get("content") or "") for m in context) // 4)
        usage = LLMUsage(
            prompt_tokens=prompt_tokens, completion_tokens=20, total_tokens=prompt_tokens + 20
        )
        if scenario.conversation:
            return LLMCallResult(
                content=f"Answer {iteration}. {scenario.reply_content}",
                cost=cost,
                currency="USD",
                usage=usage,
            )
        if iteration >= scenario.iterations:
            name = "completion"
            calls = [{"result": f"done after {iteration}", "artifacts": []}]
        elif scenario.dynamic_sources and (
            source := _source_to_activate(iteration, scenario.iterations, request.tools or [])
        ):
            name = "activate_tool_source"
            calls = [{"source_name": source}]
        else:
            name = "work_step"
            calls = [{"step": iteration}] * scenario.tools_per_turn
        return LLMCallResult(
            content=f"Step {iteration}. {scenario.reply_content}",
            tool_calls=[
                {
                    "id": f"call_{iteration}_{index}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
                for index, arguments in enumerate(calls)
            ],
            cost=cost,
            currency="USD",
            usage=usage,
        )

    @activity.defn(name="execute_mcp_tool_activity")
    async def execute_tool(request: MCPToolRequest) -> MCPToolResult:
        if scenario.tool_delay_seconds:
            await asyncio.sleep(scenario.tool_delay_seconds)
        return MCPToolResult(success=True, result=scenario.tool_output, source="builtin")

    @activity.defn(name="publish_workflow_events_activity")
    async def publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
        batch = [json.loads(raw) for raw in request.events_json]
        key = tuple(event["event_id"] for event in batch)
        scenario.publish_attempts[key] += 1
        if scenario.publish_failures_on_iteration is not None and any(
            event["event_type"] == "IterationStarted"
            and event["data"].get("iteration") == scenario.publish_failures_on_iteration
            for event in batch
        ):
            if scenario.publish_attempts[key] <= scenario.publish_failures:
                raise RuntimeError("event store unavailable")
        if (
            scenario.hold_continue_as_new_publish
            and not scenario.continue_as_new_publishing.is_set()
            and any(event["event_type"] == "WorkflowContinuedAsNew" for event in batch)
        ):
            scenario.continue_as_new_publishing.set()
            await scenario.continue_as_new_released.wait()
        for event in batch:
            if event["event_id"] not in scenario.events:
                scenario.event_order.append(event["event_id"])
            scenario.events[event["event_id"]] = event
        return WorkflowEventsResult(success=True, events_published=len(batch))

    @activity.defn(name="compact_messages_activity")
    async def compact(request: CompactMessagesRequest) -> CompactMessagesResult:
        window = request.conversation
        end_seq = scenario.write(window, request.pending)
        head, tail = scenario.window_messages(window, end_seq)
        count = compactable_prefix([scenario.log[seq] for seq in tail], request.keep_recent)
        if count == 0:
            return CompactMessagesResult(
                conversation=window.model_copy(update={"next_seq": end_seq}),
                summary="",
                original_message_count=0,
                estimated_tokens_saved=0,
                context_tokens=estimate_tokens_for_messages(
                    [scenario.log[seq] for seq in (*head, *tail)]
                ),
            )
        scenario.compactions += 1
        summary_seq = end_seq
        scenario.log[summary_seq] = {
            "role": "user",
            "content": f"[Previous conversation summary]\n{count} earlier entries.",
        }
        new_head = [head[0], summary_seq]
        kept = tail[count:]
        return CompactMessagesResult(
            conversation=ConversationWindow(
                task_id=window.task_id,
                head_seqs=new_head,
                tail_start=kept[0],
                next_seq=summary_seq + 1,
            ),
            summary=f"{count} earlier entries.",
            original_message_count=count,
            estimated_tokens_saved=1000,
            context_tokens=estimate_tokens_for_messages(
                [scenario.log[seq] for seq in (*new_head, *kept)]
            ),
            cost=scenario.compaction_cost,
            usage=LLMUsage(prompt_tokens=1000, completion_tokens=50, total_tokens=1050),
        )

    @activity.defn(name="update_task_status_activity")
    async def update_status(request: UpdateTaskStatusRequest) -> bool:
        if request.conversation is not None:
            scenario.write(request.conversation, request.conversation_pending)
        return True

    @activity.defn(name="validate_artifacts_activity")
    async def validate_artifacts(request: ArtifactValidationRequest) -> ArtifactValidationResult:
        return ArtifactValidationResult(state="passed", generation=0)

    return [
        build_config,
        discover_tools,
        discover_providers,
        resolve_model,
        call_llm,
        execute_tool,
        publish_events,
        compact,
        update_status,
        validate_artifacts,
    ]


def _request(
    scenario: Scenario,
    *,
    budget_usd: str = "1000",
    max_tokens: int = 1_000_000_000,
    max_tool_calls_per_turn: int = 10,
) -> AgentExecutionRequest:
    turns = max(scenario.iterations, 1) + 20
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="long-run-user",
        workspace_id="long-run-workspace",
        task_query="Work through the whole job.",
        effective_policy={
            "budget": {"run_budget_usd": budget_usd},
            "tokens": {"max_tokens": max_tokens, "max_tokens_per_call": 100_000},
            "execution": {
                "max_model_turns": turns,
                "max_tool_calls_per_turn": max_tool_calls_per_turn,
                "max_tool_calls_total": turns * 10,
            },
        },
        workflow_metadata={} if scenario.conversation else {"source": "agent_delegation"},
    )


@pytest.fixture
async def long_run_env():
    env = await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter,
        download_dest_dir=temporal_download_dir(),
        dev_server_extra_args=[
            "--dynamic-config-value",
            f"limit.historyCount.suggestContinueAsNew={_CONTINUE_AS_NEW_EVENTS}",
        ],
    )
    try:
        yield env
    finally:
        await env.shutdown()


class _Run:
    def __init__(self, client: Client, scenario: Scenario):
        self.client = client
        self.scenario = scenario
        self.task_queue = f"long-run-{uuid.uuid4()}"
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        self._worker = Worker(
            client,
            task_queue=self.task_queue,
            workflows=[AgentExecutionWorkflow],
            activities=_activities(scenario),
            activity_executor=self._executor,
            workflow_runner=create_workflow_runner(),
        )

    async def __aenter__(self) -> _Run:
        await self._worker.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._worker.__aexit__(*exc)
        self._executor.shutdown(wait=False)

    async def start(self, request: AgentExecutionRequest) -> WorkflowHandle:
        return await self.client.start_workflow(
            AgentExecutionWorkflow.run,
            request,
            id=f"long-run-{request.task_id}",
            task_queue=self.task_queue,
            execution_timeout=timedelta(minutes=10),
        )

    async def run_count(self, handle: WorkflowHandle) -> int:
        count = 0
        async for _ in self.client.list_workflows(f"WorkflowId = '{handle.id}'"):
            count += 1
        return count


def _assert_every_iteration_published_once(scenario: Scenario, iterations: int) -> None:
    per_iteration = collections.Counter(
        (event["event_type"], event["data"].get("iteration")) for event in scenario.events.values()
    )
    missing_or_repeated = [
        (event_type, iteration, per_iteration[(event_type, iteration)])
        for iteration in range(1, iterations + 1)
        for event_type in (
            "IterationStarted",
            "llm.call.started",
            "llm.call.completed",
            "IterationCompleted",
        )
        if per_iteration[(event_type, iteration)] != 1
    ]
    assert missing_or_repeated == []


async def _wait_until(predicate, timeout: float = 60.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition was not reached in time")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_long_run_publishes_every_iteration_across_continue_as_new(long_run_env):
    scenario = Scenario(iterations=40, tool_output="x" * 500)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        result = await handle.result()

        assert result.success is True
        assert await run.run_count(handle) >= 5
    _assert_every_iteration_published_once(scenario, 40)
    assert len(scenario.published("task.completed")) == 1


@pytest.mark.asyncio
async def test_message_sent_while_continuing_as_new_reaches_the_model(long_run_env):
    scenario = Scenario(iterations=20, hold_continue_as_new_publish=True)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        await asyncio.wait_for(scenario.continue_as_new_publishing.wait(), timeout=60)
        await handle.signal(
            AgentExecutionWorkflow.workflow_command,
            args=["queue_message", {"content": "also check the edge cases"}],
        )
        scenario.continue_as_new_released.set()
        result = await handle.result()

        assert result.success is True
    assert "also check the edge cases" in scenario.user_messages_seen()
    assert len(scenario.published("MessageQueued")) == 1


@pytest.mark.asyncio
async def test_conversation_continues_as_new_between_turns(long_run_env):
    scenario = Scenario(conversation=True, reply_content="word " * 200)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        turns = 8
        for turn in range(1, turns):
            await _wait_until(lambda turn=turn: len(scenario.published("task.completed")) >= turn)
            await handle.signal(
                AgentExecutionWorkflow.workflow_command,
                args=["queue_message", {"content": f"follow-up {turn}"}],
            )
        await _wait_until(lambda: len(scenario.published("task.completed")) >= turns)
        runs = await run.run_count(handle)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()

    assert {f"follow-up {turn}" for turn in range(1, turns)} <= scenario.user_messages_seen()
    assert runs >= 2


@pytest.mark.asyncio
async def test_compaction_replaces_old_turns_with_a_summary(long_run_env):
    scenario = Scenario(iterations=30, context_window=8_000, tool_output="y" * 2_000)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        result = await asyncio.wait_for(handle.result(), timeout=120)

    assert result.success is True
    assert scenario.compactions >= 1
    assert scenario.published("ContextCompacted")


@pytest.mark.asyncio
async def test_compaction_that_crosses_the_budget_is_persisted_before_the_run_stops(
    long_run_env,
):
    """The summarizing call was paid for; it must reach the log as a metered model call.

    Usage metering projects llm.call.completed and keys a fact on task, execution,
    iteration, model, token counts and the run's cumulative cost, so the
    compaction event carries the turn events' identity and the total after its
    own cost.
    """
    scenario = Scenario(
        iterations=30, context_window=8_000, tool_output="y" * 2_000, compaction_cost="5"
    )
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario, budget_usd="1"))
        result = await asyncio.wait_for(handle.result(), timeout=120)

    assert result.success is False
    assert result.failure_reason == "budget_exceeded"
    assert scenario.compactions == 1
    events = [scenario.events[event_id] for event_id in scenario.event_order]
    completed = [e for e in events if e["event_type"] == "llm.call.completed"]
    [metered] = [e for e in completed if e["data"].get("purpose") == "compaction"]
    turns = [e for e in completed if e["data"].get("purpose") is None]
    last_turn = turns[-1]
    started = [e for e in events if e["event_type"] == "IterationStarted"]

    data = metered["data"]
    assert to_money(data["cost"]) == to_money("5")
    assert data["usage"]["usage"] == {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "total_tokens": 1050,
    }
    assert data["model_id"] == "model-long-run"
    assert data["task_id"] == last_turn["data"]["task_id"]
    assert data["execution_id"] == last_turn["data"]["execution_id"]
    assert data["iteration"] == started[-1]["data"]["iteration"]
    assert to_money(data["total_cost"]) == to_money(last_turn["data"]["total_cost"]) + 5
    assert scenario.published("ContextCompacted")
    assert events.index(metered) < next(
        index for index, e in enumerate(events) if e["event_type"] == "task.failed"
    )


@pytest.mark.asyncio
async def test_event_store_outage_does_not_fail_the_run(long_run_env):
    scenario = Scenario(iterations=8, publish_failures_on_iteration=4, publish_failures=3)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        result = await handle.result()

    assert result.success is True
    _assert_every_iteration_published_once(scenario, 8)


@pytest.mark.asyncio
async def test_model_outage_across_three_attempts_does_not_fail_the_run(long_run_env):
    scenario = Scenario(iterations=3, llm_failures=3)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        result = await handle.result()

    assert result.success is True


@pytest.mark.asyncio
async def test_large_context_model_does_not_carry_the_conversation_in_payloads(long_run_env):
    scenario = Scenario(
        iterations=30, context_window=1_000_000, reply_content="z" * 100_000, tool_output="ok"
    )
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        result = await asyncio.wait_for(handle.result(), timeout=240)

    assert result.success is True
    assert scenario.compactions >= 1
    assert max(scenario.llm_request_bytes) < _TEMPORAL_BLOB_LIMIT_BYTES


@pytest.mark.asyncio
async def test_budget_warning_is_sent_once_across_continue_as_new(long_run_env):
    scenario = Scenario(iterations=18, first_call_cost="0.85", call_cost="0.001")
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario, budget_usd="1.00"))
        result = await handle.result()

        assert result.success is True
        assert await run.run_count(handle) >= 3
    assert len(scenario.published("BudgetWarning")) == 1


@pytest.mark.asyncio
async def test_too_many_tool_calls_in_one_turn_are_handed_back_to_the_model(long_run_env):
    scenario = Scenario(iterations=4, tools_per_turn=3)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario, max_tool_calls_per_turn=2))
        result = await handle.result()

    assert result.success is True
    tool_replies = [
        message.get("content") or ""
        for message in scenario.llm_requests[1].messages
        if message.get("role") == "tool"
    ]
    assert tool_replies
    assert all("per turn" in reply for reply in tool_replies)


@pytest.mark.asyncio
async def test_dynamic_tool_catalog_survives_continue_as_new(long_run_env):
    scenario = Scenario(iterations=20, context_strategy="dynamic", dynamic_sources=True)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        result = await handle.result()

        assert result.success is True
        assert await run.run_count(handle) >= 3
    tool_replies = [
        message.get("content") or ""
        for request in scenario.llm_requests
        for message in request.messages
        if message.get("name") == "activate_tool_source"
    ]
    assert any("archive" in reply for reply in tool_replies)
    assert not any("catalog not available" in reply for reply in tool_replies)
    assert any(
        (tool.get("function") or {}).get("name") == "archive_step"
        for tool in scenario.llm_requests[-1].tools or []
    )


@pytest.mark.asyncio
async def test_cancelled_run_reports_cancelled_not_failed(long_run_env):
    scenario = Scenario(iterations=10, llm_delay_seconds=30)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        await _wait_until(lambda: bool(scenario.published("llm.call.started")))
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        await _wait_until(lambda: bool(scenario.published("task.cancelled")), timeout=20)

    assert scenario.published("task.failed") == []
    assert scenario.published("llm.call.failed") == []


@pytest.mark.asyncio
async def test_cancel_during_a_tool_call_stops_the_run(long_run_env):
    scenario = Scenario(iterations=10, tool_delay_seconds=30)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        await _wait_until(lambda: bool(scenario.published("tool.call")))
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), timeout=20)

    assert len(scenario.llm_requests) == 1
    assert scenario.published("task.cancelled")


@pytest.mark.asyncio
async def test_the_conversation_lives_in_the_log_not_in_payloads(long_run_env):
    scenario = Scenario(iterations=20, context_window=1_000_000, tool_output="w" * 50_000)
    async with _Run(long_run_env.client, scenario) as run:
        handle = await run.start(_request(scenario))
        result = await handle.result()

    assert result.success is True
    log_bytes = sum(len(json.dumps(message)) for message in scenario.log.values())
    assert log_bytes > 900_000
    assert max(scenario.llm_request_bytes) < 200_000
    assert [scenario.log[seq]["role"] for seq in (0, 1)] == ["system", "user"]
    assert scenario.log[max(scenario.log)].get("name") == "completion"
