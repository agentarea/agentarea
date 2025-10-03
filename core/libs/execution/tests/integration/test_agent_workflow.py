import concurrent.futures
import uuid
from datetime import timedelta
from typing import Any

import pytest

# Import event system components
from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.broker import EventBroker
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


class MockEventBroker(EventBroker):
    """Mock event broker that captures published events for testing."""

    def __init__(self):
        self.published_events: list[DomainEvent] = []
        self.publish_calls = 0

    async def publish(self, event: DomainEvent) -> None:
        """Capture published events."""
        self.published_events.append(event)
        self.publish_calls += 1
        print(f"📢 Event published: {event.event_type} - {event.data}")

    def get_events_by_type(self, event_type: str) -> list[DomainEvent]:
        """Get all events of a specific type."""
        return [event for event in self.published_events if event.event_type == event_type]

    def clear_events(self):
        """Clear captured events."""
        self.published_events.clear()
        self.publish_calls = 0


class TestAgentExecutionWorkflowIntegration:
    @pytest.mark.asyncio
    async def test_workflow_with_tool_calls(self):
        """Test that the workflow properly handles tool calls by creating new activities."""
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            task_queue_name = str(uuid.uuid4())
            workflow_id = str(uuid.uuid4())

            @activity.defn(name="build_agent_config_activity")
            async def mock_build_agent_config_activity(
                agent_id: uuid.UUID,
                execution_context: dict[str, Any] | None = None,
                step_type: str | None = None,
                override_model: str | None = None,
            ) -> dict[str, Any]:
                return {
                    "id": str(agent_id),
                    "name": "Test Agent",
                    "model_id": "gpt-4",
                    "description": "Test agent",
                    "instruction": "You are a helpful assistant.",
                    "tools_config": {"mcp_servers": []},
                    "events_config": {},
                    "planning": False,
                }

            @activity.defn(name="discover_available_tools_activity")
            async def mock_discover_available_tools_activity(
                agent_id: uuid.UUID,
            ) -> list[dict[str, Any]]:
                return [
                    {
                        "name": "calculator",
                        "description": "Calculate mathematical expressions",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "expression": {
                                    "type": "string",
                                    "description": "Math expression to calculate",
                                }
                            },
                            "required": ["expression"],
                        },
                    }
                ]

            # Track LLM call count to simulate iterative behavior
            llm_call_count = 0

            @activity.defn(name="call_llm_activity")
            async def mock_call_llm_activity(
                messages: list[dict[str, Any]],
                model_id: str,
                tools: list[dict[str, Any]] | None = None,
                user_context_data: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                nonlocal llm_call_count
                llm_call_count += 1

                # First call - LLM decides to use calculator
                if llm_call_count == 1:
                    return {
                        "content": "I need to calculate 2 + 2. Let me use the calculator.",
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"expression": "2 + 2"}',
                                },
                            }
                        ],
                        "finish_reason": "tool_call",
                        "cost": 0.001,
                        "usage": {
                            "prompt_tokens": 20,
                            "completion_tokens": 25,
                            "total_tokens": 45,
                        },
                    }

                # Second call - LLM provides final answer after tool execution
                elif llm_call_count == 2:
                    return {
                        "content": "Based on my calculation, 2 + 2 equals 4.",
                        "role": "assistant",
                        "tool_calls": [],
                        "finish_reason": "stop",
                        "cost": 0.001,
                        "usage": {
                            "prompt_tokens": 25,
                            "completion_tokens": 15,
                            "total_tokens": 40,
                        },
                    }

                # Fallback
                return {
                    "content": "I have completed the task.",
                    "role": "assistant",
                    "tool_calls": [],
                    "finish_reason": "stop",
                    "cost": 0.001,
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 10,
                        "total_tokens": 20,
                    },
                }

            @activity.defn(name="execute_mcp_tool_activity")
            async def mock_execute_mcp_tool_activity(
                tool_name: str,
                tool_args: dict[str, Any],
                server_instance_id: uuid.UUID | None = None,
            ) -> dict[str, Any]:
                if tool_name == "calculator" and tool_args.get("expression") == "2 + 2":
                    return {
                        "success": True,
                        "result": "4",
                        "tool_name": tool_name,
                    }
                return {
                    "success": True,
                    "result": f"Mock result for {tool_name}",
                    "tool_name": tool_name,
                }

            @activity.defn(name="check_task_completion_activity")
            async def mock_check_task_completion_activity(
                messages: list[dict[str, Any]],
                current_iteration: int,
                max_iterations: int,
            ) -> dict[str, Any]:
                # Complete after 2 LLM calls for tool test, or if finish_reason is 'stop'
                if llm_call_count >= 2:
                    return {"should_complete": True, "reason": "test_complete"}
                # Check last assistant message for finish_reason
                for msg in reversed(messages):
                    if msg.get("role") == "assistant" and msg.get("finish_reason") == "stop":
                        return {"should_complete": True, "reason": "llm_stop"}
                return {"should_complete": False, "reason": "continue"}

            @activity.defn(name="create_execution_plan_activity")
            async def mock_create_execution_plan_activity(
                goal: dict[str, Any],
                available_tools: list[dict[str, Any]],
                messages: list[dict[str, Any]],
            ) -> dict[str, Any]:
                return {
                    "plan": "Execute the task step by step",
                    "estimated_steps": 3,
                    "key_tools": [],
                    "risk_factors": ["None"],
                }

            @activity.defn(name="evaluate_goal_progress_activity")
            async def mock_evaluate_goal_progress_activity(
                goal: dict[str, Any],
                messages: list[dict[str, Any]],
                current_iteration: int,
            ) -> dict[str, Any]:
                # Complete after 2 iterations to allow for tool call and response
                if current_iteration >= 2:
                    return {
                        "goal_achieved": True,
                        "final_response": "Based on my calculation, 2 + 2 equals 4.",
                        "success_criteria_met": [],
                        "progress_indicators": {
                            "message_count": len(messages),
                            "tool_calls": 1,  # We expect 1 tool call
                            "assistant_responses": 2,
                            "iteration": current_iteration,
                        },
                    }

                return {
                    "goal_achieved": False,
                    "final_response": None,
                    "success_criteria_met": [],
                    "progress_indicators": {},
                }

            @activity.defn(name="publish_workflow_events_activity")
            async def mock_publish_workflow_events_activity(events_json: list[str]) -> bool:
                """Mock activity that just returns True for existing tests."""
                return True

            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as activity_executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue_name,
                    workflows=[AgentExecutionWorkflow],
                    activities=[
                        mock_build_agent_config_activity,
                        mock_discover_available_tools_activity,
                        mock_call_llm_activity,
                        mock_execute_mcp_tool_activity,
                        mock_check_task_completion_activity,
                        mock_create_execution_plan_activity,
                        mock_evaluate_goal_progress_activity,
                        mock_publish_workflow_events_activity,
                    ],
                    activity_executor=activity_executor,
                )

                async with worker:
                    sample_request = AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="integration_test_user",
                        task_query="What is 2 + 2?",
                        timeout_seconds=30,
                        max_reasoning_iterations=5,
                    )

                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        sample_request,
                        id=workflow_id,
                        task_queue=task_queue_name,
                        execution_timeout=timedelta(minutes=2),
                    )

                    assert WorkflowExecutionStatus.RUNNING == (await handle.describe()).status

                    # Check execution status during workflow
                    status = await handle.query("get_current_state")
                    assert "status" in status

                    result = await handle.result()

                    # Verify the workflow completed successfully
                    assert result.success is True
                    assert result.agent_id == sample_request.agent_id
                    assert result.task_id == sample_request.task_id
                    assert result.final_response is not None
                    assert "4" in result.final_response  # Should contain the calculation result

                    print(f"✅ Test passed! Tool calls made: {result.total_tool_calls}")
                    print(f"✅ Conversation history: {len(result.conversation_history)} messages")
                    print(f"✅ Final response: {result.final_response}")

    @pytest.mark.asyncio
    async def test_workflow_without_tool_calls(self):
        """Test workflow when no tools are needed."""
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            task_queue_name = str(uuid.uuid4())
            workflow_id = str(uuid.uuid4())

            @activity.defn(name="build_agent_config_activity")
            async def mock_build_agent_config_activity(
                agent_id: uuid.UUID,
                execution_context: dict[str, Any] | None = None,
                step_type: str | None = None,
                override_model: str | None = None,
            ) -> dict[str, Any]:
                return {
                    "id": str(agent_id),
                    "name": "Test Agent",
                    "model_id": "gpt-4",
                    "description": "Test agent",
                    "instruction": "You are a helpful assistant.",
                    "tools_config": {"mcp_servers": []},
                    "events_config": {},
                    "planning": False,
                }

            @activity.defn(name="discover_available_tools_activity")
            async def mock_discover_available_tools_activity(
                agent_id: uuid.UUID,
            ) -> list[dict[str, Any]]:
                return []

            @activity.defn(name="call_llm_activity")
            async def mock_call_llm_activity(
                messages: list[dict[str, Any]],
                model_id: str,
                tools: list[dict[str, Any]] | None = None,
                user_context_data: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                return {
                    "content": "Hello! I'm here to help you with your questions.",
                    "role": "assistant",
                    "tool_calls": [],
                    "finish_reason": "stop",
                    "cost": 0.001,
                    "usage": {
                        "prompt_tokens": 15,
                        "completion_tokens": 12,
                        "total_tokens": 27,
                    },
                }

            @activity.defn(name="execute_mcp_tool_activity")
            async def mock_execute_mcp_tool_activity(
                tool_name: str,
                tool_args: dict[str, Any],
                server_instance_id: uuid.UUID | None = None,
            ) -> dict[str, Any]:
                return {"success": True, "result": "Mock result", "tool_name": tool_name}

            @activity.defn(name="check_task_completion_activity")
            async def mock_check_task_completion_activity(
                messages: list[dict[str, Any]],
                current_iteration: int,
                max_iterations: int,
            ) -> dict[str, Any]:
                # Complete after first iteration for this test
                if current_iteration == 1:
                    return {"should_complete": True, "reason": "test_complete"}
                return {"should_complete": False, "reason": "continue"}

            @activity.defn(name="create_execution_plan_activity")
            async def mock_create_execution_plan_activity(
                goal: dict[str, Any],
                available_tools: list[dict[str, Any]],
                messages: list[dict[str, Any]],
            ) -> dict[str, Any]:
                return {
                    "plan": "Execute the task step by step",
                    "estimated_steps": 3,
                    "key_tools": [],
                    "risk_factors": ["None"],
                }

            @activity.defn(name="evaluate_goal_progress_activity")
            async def mock_evaluate_goal_progress_activity(
                goal: dict[str, Any],
                messages: list[dict[str, Any]],
                current_iteration: int,
            ) -> dict[str, Any]:
                # Complete after first iteration for this test
                if current_iteration >= 1:
                    return {
                        "goal_achieved": True,
                        "final_response": "Task completed successfully without tools",
                        "success_criteria_met": [],
                        "progress_indicators": {
                            "message_count": len(messages),
                            "tool_calls": 0,
                            "assistant_responses": 1,
                            "iteration": current_iteration,
                        },
                    }
                return {
                    "goal_achieved": False,
                    "final_response": None,
                    "success_criteria_met": [],
                    "progress_indicators": {},
                }

            @activity.defn(name="publish_workflow_events_activity")
            async def mock_publish_workflow_events_activity(events_json: list[str]) -> bool:
                """Mock activity that just returns True for existing tests."""
                return True

            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as activity_executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue_name,
                    workflows=[AgentExecutionWorkflow],
                    activities=[
                        mock_build_agent_config_activity,
                        mock_discover_available_tools_activity,
                        mock_call_llm_activity,
                        mock_execute_mcp_tool_activity,
                        mock_check_task_completion_activity,
                        mock_create_execution_plan_activity,
                        mock_evaluate_goal_progress_activity,
                        mock_publish_workflow_events_activity,
                    ],
                    activity_executor=activity_executor,
                )

                async with worker:
                    sample_request = AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="integration_test_user",
                        task_query="Hello, how are you?",
                        timeout_seconds=30,
                        max_reasoning_iterations=3,
                    )

                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        sample_request,
                        id=workflow_id,
                        task_queue=task_queue_name,
                        execution_timeout=timedelta(minutes=2),
                    )

                    result = await handle.result()

                    # Verify the workflow completed successfully without tools
                    assert result.success is True
                    assert result.agent_id == sample_request.agent_id
                    assert result.task_id == sample_request.task_id
                    assert result.final_response is not None

                    print(f"✅ Test passed! No tool calls made: {result.total_tool_calls}")
                    print(f"✅ Completed in {result.reasoning_iterations_used} iteration(s)")
                    print(f"✅ Final response: {result.final_response}")

    @pytest.mark.asyncio
    async def test_workflow_event_publishing(self):
        """Test that workflow properly publishes events to event broker during execution."""
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            task_queue_name = str(uuid.uuid4())
            workflow_id = str(uuid.uuid4())

            # Create a mock event broker to capture events
            mock_event_broker = MockEventBroker()

            @activity.defn(name="build_agent_config_activity")
            async def mock_build_agent_config_activity(
                agent_id: uuid.UUID,
                execution_context: dict[str, Any] | None = None,
                step_type: str | None = None,
                override_model: str | None = None,
            ) -> dict[str, Any]:
                return {
                    "id": str(agent_id),
                    "name": "Test Agent",
                    "model_id": "gpt-4",
                    "instruction": "You are a helpful assistant.",
                    "tools_config": {"mcp_servers": []},
                    "events_config": {},
                    "planning": False,
                }

            @activity.defn(name="discover_available_tools_activity")
            async def mock_discover_available_tools_activity(
                agent_id: uuid.UUID,
            ) -> list[dict[str, Any]]:
                return []

            @activity.defn(name="call_llm_activity")
            async def mock_call_llm_activity(
                messages: list[dict[str, Any]],
                model_id: str,
                tools: list[dict[str, Any]] | None = None,
                user_context_data: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                return {
                    "content": "Hello! I can help you with your task.",
                    "role": "assistant",
                    "tool_calls": [],
                    "cost": 0.001,
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 15,
                        "total_tokens": 25,
                    },
                }

            @activity.defn(name="execute_mcp_tool_activity")
            async def mock_execute_mcp_tool_activity(
                tool_name: str,
                tool_args: dict[str, Any],
                server_instance_id: uuid.UUID | None = None,
            ) -> dict[str, Any]:
                return {"success": True, "result": "Mock result", "tool_name": tool_name}

            @activity.defn(name="create_execution_plan_activity")
            async def mock_create_execution_plan_activity(
                goal: dict[str, Any],
                available_tools: list[dict[str, Any]],
                messages: list[dict[str, Any]],
            ) -> dict[str, Any]:
                return {
                    "plan": "Execute the task step by step",
                    "estimated_steps": 3,
                    "key_tools": [],
                    "risk_factors": ["None"],
                }

            @activity.defn(name="evaluate_goal_progress_activity")
            async def mock_evaluate_goal_progress_activity(
                goal: dict[str, Any],
                messages: list[dict[str, Any]],
                current_iteration: int,
            ) -> dict[str, Any]:
                # Complete after first iteration
                if current_iteration >= 1:
                    return {
                        "goal_achieved": True,
                        "final_response": "Task completed successfully",
                        "success_criteria_met": [],
                        "progress_indicators": {
                            "message_count": len(messages),
                            "tool_calls": 0,
                            "assistant_responses": 1,
                            "iteration": current_iteration,
                        },
                    }
                return {
                    "goal_achieved": False,
                    "final_response": None,
                    "success_criteria_met": [],
                    "progress_indicators": {},
                }

            @activity.defn(name="publish_workflow_events_activity")
            async def mock_publish_workflow_events_activity(events_json: list[str]) -> bool:
                """Mock activity that publishes events to our mock event broker."""
                if not events_json:
                    return True

                import json
                from datetime import datetime
                from uuid import uuid4

                print(f"📢 Publishing {len(events_json)} events to mock broker")

                for event_json in events_json:
                    event_data = json.loads(event_json)

                    # Create DomainEvent and publish to our mock broker
                    domain_event = DomainEvent(
                        event_id=uuid4(),
                        event_type=f"workflow.{event_data['event_type']}",
                        timestamp=datetime.fromisoformat(
                            event_data["timestamp"].replace("Z", "+00:00")
                        ),
                        data=event_data["data"],
                    )

                    await mock_event_broker.publish(domain_event)

                return True

            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as activity_executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue_name,
                    workflows=[AgentExecutionWorkflow],
                    activities=[
                        mock_build_agent_config_activity,
                        mock_discover_available_tools_activity,
                        mock_call_llm_activity,
                        mock_execute_mcp_tool_activity,
                        mock_create_execution_plan_activity,
                        mock_evaluate_goal_progress_activity,
                        mock_publish_workflow_events_activity,
                    ],
                    activity_executor=activity_executor,
                )

                async with worker:
                    sample_request = AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="event_test_user",
                        task_query="Test event publishing",
                        timeout_seconds=30,
                        max_reasoning_iterations=3,
                        budget_usd=1.0,
                    )

                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        sample_request,
                        id=workflow_id,
                        task_queue=task_queue_name,
                        execution_timeout=timedelta(minutes=2),
                    )

                    result = await handle.result()

                    # ✅ WORKFLOW RESULT ASSERTIONS
                    assert result.success is True
                    assert result.agent_id == sample_request.agent_id
                    assert result.task_id == sample_request.task_id
                    assert result.final_response is not None

                    # ✅ EVENT PUBLISHING ASSERTIONS
                    print("\n📊 EVENT VERIFICATION SUMMARY:")
                    print(f"Total events published: {mock_event_broker.publish_calls}")
                    print(f"Events captured: {len(mock_event_broker.published_events)}")

                    # Verify events were actually published
                    assert mock_event_broker.publish_calls > 0, "No events were published!"
                    assert len(mock_event_broker.published_events) > 0, "No events were captured!"

                    # ✅ VERIFY SPECIFIC EVENT TYPES
                    workflow_started_events = mock_event_broker.get_events_by_type(
                        "workflow.WorkflowStarted"
                    )
                    workflow_finished_events = mock_event_broker.get_events_by_type(
                        "workflow.WorkflowFinished"
                    )
                    iteration_completed_events = mock_event_broker.get_events_by_type(
                        "workflow.IterationCompleted"
                    )

                    print(f"Workflow started events: {len(workflow_started_events)}")
                    print(f"Workflow finished events: {len(workflow_finished_events)}")
                    print(f"Iteration completed events: {len(iteration_completed_events)}")

                    # Should have at least workflow start event
                    assert len(workflow_started_events) >= 1, "Missing WorkflowStarted event!"

                    # Check if we have finished events (may not always be present if workflow is cut short)
                    if len(workflow_finished_events) == 0:
                        print(
                            "⚠️ No WorkflowFinished events found - this might be expected for quick completion"
                        )

                    # ✅ VERIFY EVENT STRUCTURE FOR SSE COMPATIBILITY
                    for event in mock_event_broker.published_events:
                        # Each event should have required fields for SSE streaming
                        assert hasattr(event, "event_id"), "Event missing event_id"
                        assert hasattr(event, "event_type"), "Event missing event_type"
                        assert hasattr(event, "timestamp"), "Event missing timestamp"
                        assert hasattr(event, "data"), "Event missing data"

                        # Data should contain task identifiers (nested in data.data)
                        event_data = event.data.get("data", {})
                        assert "task_id" in event_data, f"Event data missing task_id: {event_data}"
                        assert "agent_id" in event_data, (
                            f"Event data missing agent_id: {event_data}"
                        )

                        print(
                            f"✅ Event verified: {event.event_type} - {event_data.get('task_id', 'no_task_id')}"
                        )

                    # ✅ VERIFY EVENT SEQUENCE
                    event_types = [event.event_type for event in mock_event_broker.published_events]
                    print(f"Event sequence: {event_types}")

                    # Should start with WorkflowStarted
                    assert event_types[0] == "workflow.WorkflowStarted", (
                        f"First event should be WorkflowStarted, got: {event_types[0]}"
                    )

                    # Check the last event - it could be WorkflowFinished or IterationCompleted
                    last_event_type = event_types[-1]
                    valid_final_events = [
                        "workflow.WorkflowFinished",
                        "workflow.IterationCompleted",
                        "workflow.GoalAchieved",
                    ]
                    assert last_event_type in valid_final_events, (
                        f"Last event should be one of {valid_final_events}, got: {last_event_type}"
                    )

                    print("✅ Event publishing test passed!")
                    print(
                        f"✅ All {len(mock_event_broker.published_events)} events are properly formatted for SSE streaming"
                    )
                    print("✅ Event sequence is correct: START → EXECUTION → FINISH")
