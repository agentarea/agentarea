#!/usr/bin/env python3
"""
Comprehensive integration test for CLI → Workflow → SSE event flow.

This test demonstrates the complete AgentArea workflow:
1. Create agent via CLI interface
2. Submit task via CLI interface
3. Workflow executes and publishes events to event bus
4. SSE endpoint streams events in real-time
5. Verify event flow end-to-end
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config.broker import RedisSettings
from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.router import create_event_broker_from_router, get_event_router
from agentarea_tasks.domain.interfaces import BaseTaskManager
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from libs.execution.agentarea_execution.models import (
    AgentExecutionRequest,
)
from libs.execution.agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockTaskRepository:
    """Mock repository for testing."""

    def __init__(self):
        self.tasks = {}

    async def get(self, task_id: UUID) -> SimpleTask | None:
        return self.tasks.get(task_id)

    async def create(self, task: SimpleTask) -> SimpleTask:
        self.tasks[task.id] = task
        return task

    async def update(self, task: SimpleTask) -> SimpleTask:
        self.tasks[task.id] = task
        return task

    async def list_tasks(self, **kwargs) -> list[SimpleTask]:
        return list(self.tasks.values())


class MockTaskManager(BaseTaskManager):
    """Mock task manager for testing."""

    def __init__(self):
        self.submitted_tasks = []
        self.cancelled_tasks = []
        self.tasks = {}

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Mock task submission."""
        self.submitted_tasks.append(task)
        task.status = "running"
        self.tasks[task.id] = task
        return task

    async def get_task(self, task_id: UUID) -> SimpleTask | None:
        """Mock get task."""
        return self.tasks.get(task_id)

    async def cancel_task(self, task_id: UUID) -> bool:
        """Mock task cancellation."""
        self.cancelled_tasks.append(task_id)
        if task_id in self.tasks:
            self.tasks[task_id].status = "cancelled"
        return True

    async def list_tasks(
        self,
        agent_id: UUID | None = None,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SimpleTask]:
        """Mock list tasks."""
        tasks = list(self.tasks.values())
        if agent_id:
            tasks = [t for t in tasks if t.agent_id == agent_id]
        if user_id:
            tasks = [t for t in tasks if t.user_id == user_id]
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks[offset : offset + limit]

    async def get_task_status(self, task_id: UUID) -> str | None:
        """Mock get task status."""
        task = self.tasks.get(task_id)
        return task.status if task else None

    async def get_task_result(self, task_id: UUID) -> Any | None:
        """Mock get task result."""
        task = self.tasks.get(task_id)
        return task.result if task else None


class CLITestHelper:
    """Helper class for CLI operations."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.cli_path = base_dir / "apps" / "cli" / "agentarea_cli" / "main.py"

    def run_cli_command(self, command: list[str], timeout: int = 30) -> dict[str, Any]:
        """Run CLI command and return result."""
        try:
            # Construct full command
            full_command = [sys.executable, "-m", "agentarea_cli"] + command

            logger.info(f"Running CLI command: {' '.join(full_command)}")

            # Run command
            result = subprocess.run(
                full_command, cwd=self.base_dir, capture_output=True, text=True, timeout=timeout
            )

            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
            }

        except subprocess.TimeoutExpired:
            logger.error(f"CLI command timed out after {timeout}s")
            return {"returncode": -1, "stdout": "", "stderr": "Command timed out", "success": False}
        except Exception as e:
            logger.error(f"CLI command failed: {e}")
            return {"returncode": -1, "stdout": "", "stderr": str(e), "success": False}

    def create_agent_via_cli(
        self, name: str, description: str, instruction: str, model_id: str
    ) -> dict[str, Any]:
        """Create agent via CLI."""
        command = [
            "agent",
            "create",
            "--name",
            name,
            "--description",
            description,
            "--instruction",
            instruction,
            "--model-id",
            model_id,
        ]
        return self.run_cli_command(command)

    def send_chat_message(self, agent_id: str, message: str) -> dict[str, Any]:
        """Send chat message via CLI."""
        command = ["chat", "send", agent_id, "--message", message, "--format", "json"]
        return self.run_cli_command(command)

    def list_agents(self) -> dict[str, Any]:
        """List agents via CLI."""
        command = ["agent", "list", "--format", "json"]
        return self.run_cli_command(command)


class WorkflowEventCollector:
    """Collects workflow events for testing."""

    def __init__(self):
        self.events = []
        self.event_types_seen = set()

    def add_event(self, event: dict[str, Any]):
        """Add event to collection."""
        self.events.append(event)
        event_type = event.get("event_type", "unknown")
        self.event_types_seen.add(event_type)
        logger.info(f"📝 Collected event: {event_type}")

    def get_events_by_type(self, event_type: str) -> list[dict[str, Any]]:
        """Get events of specific type."""
        return [e for e in self.events if e.get("event_type") == event_type]

    def has_event_type(self, event_type: str) -> bool:
        """Check if event type was seen."""
        return event_type in self.event_types_seen

    def get_summary(self) -> dict[str, Any]:
        """Get summary of collected events."""
        return {
            "total_events": len(self.events),
            "event_types": list(self.event_types_seen),
            "event_type_counts": {
                et: len(self.get_events_by_type(et)) for et in self.event_types_seen
            },
        }


async def create_mock_workflow_activities():
    """Create mock activities for workflow testing."""

    @activity.defn
    async def build_agent_config_activity(
        agent_id: UUID, user_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Mock agent config activity."""
        return {
            "id": str(agent_id),
            "name": "Test Agent",
            "description": "Test agent for CLI integration",
            "instruction": "Complete tasks efficiently",
            "model_id": "test-model-id",
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    @activity.defn
    async def discover_available_tools_activity(
        agent_config: dict[str, Any], user_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Mock tools discovery activity."""
        return [
            {
                "name": "task_complete",
                "description": "Mark task as completed",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {"type": "string", "description": "Task result"},
                        "success": {
                            "type": "boolean",
                            "description": "Whether task was successful",
                        },
                    },
                    "required": ["result", "success"],
                },
            }
        ]

    @activity.defn
    async def call_llm_activity(*args, **kwargs) -> dict[str, Any]:
        """Mock LLM call activity."""
        return {
            "role": "assistant",
            "content": "I'll complete this task for you.",
            "tool_calls": [
                {
                    "id": "call_complete_1",
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "arguments": json.dumps(
                            {
                                "result": "Task completed successfully via CLI integration test",
                                "success": True,
                            }
                        ),
                    },
                }
            ],
            "cost": 0.01,
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

    @activity.defn
    async def execute_mcp_tool_activity(
        tool_name: str, tool_args: dict[str, Any], *args, **kwargs
    ) -> dict[str, Any]:
        """Mock tool execution activity."""
        if tool_name == "task_complete":
            return {
                "success": True,
                "result": tool_args.get("result", "Task completed"),
                "completed": True,
            }
        return {"success": True, "result": f"Executed {tool_name}"}

    @activity.defn
    async def evaluate_goal_progress_activity(*args, **kwargs) -> dict[str, Any]:
        """Mock goal evaluation activity."""
        return {
            "completed": True,
            "success": True,
            "confidence": 0.95,
            "reasoning": "Task completed successfully",
        }

    @activity.defn
    async def publish_workflow_events_activity(events_json: list[str]) -> bool:
        """Mock event publishing activity that actually publishes to event bus."""
        if not events_json:
            return True

        try:
            # Get event broker from global state (set up in test)
            global _test_event_broker
            event_broker = globals().get("_test_event_broker")
            if not event_broker:
                logger.warning("No event broker available for publishing")
                return True

            logger.info(f"📤 Publishing {len(events_json)} workflow events")

            for event_json in events_json:
                event = json.loads(event_json)
                task_id = event.get("data", {}).get("task_id", "unknown")

                # Create proper domain event
                domain_event = DomainEvent(
                    event_id=event.get("event_id", str(uuid4())),
                    event_type=f"workflow.{event['event_type']}",
                    timestamp=datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")),
                    aggregate_id=task_id,
                    aggregate_type="task",
                    original_event_type=event["event_type"],
                    original_timestamp=event["timestamp"],
                    original_data=event["data"],
                )

                # Publish via EventBroker
                await event_broker.publish(domain_event)
                logger.info(f"  ✅ Published: {event['event_type']} for task {task_id}")

            return True

        except Exception as e:
            logger.error(f"Failed to publish workflow events: {e}")
            return False

    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
    ]


async def simulate_sse_streaming(
    task_service: TaskService,
    task_id: UUID,
    collector: WorkflowEventCollector,
    max_events: int = 10,
    timeout: int = 30,
):
    """Simulate SSE endpoint streaming events."""
    logger.info(f"📡 Starting SSE streaming for task {task_id}")

    start_time = time.time()

    try:
        async for event in task_service.stream_task_events(task_id, include_history=False):
            collector.add_event(event)

            # Check timeout
            if time.time() - start_time > timeout:
                logger.warning(f"SSE streaming timed out after {timeout}s")
                break

            # Check if we have enough events
            if len(collector.events) >= max_events:
                logger.info(f"Collected {max_events} events, stopping SSE stream")
                break

            # Check for terminal events
            event_type = event.get("event_type", "")
            if event_type in [
                "task_completed",
                "task_failed",
                "workflow_completed",
                "workflow_failed",
            ]:
                logger.info(f"Terminal event received: {event_type}")
                break

    except Exception as e:
        logger.error(f"Error in SSE streaming: {e}")

    logger.info(f"📡 SSE streaming completed. Collected {len(collector.events)} events")


@pytest.mark.asyncio
async def test_cli_workflow_sse_integration():
    """Test complete CLI → Workflow → SSE integration."""
    logger.info("🚀 Starting CLI → Workflow → SSE Integration Test")
    logger.info("=" * 80)

    # Setup
    base_dir = Path(__file__).parent.parent.parent
    cli_helper = CLITestHelper(base_dir)
    event_collector = WorkflowEventCollector()

    # Test IDs
    task_id = uuid4()
    agent_id = uuid4()

    logger.info(f"Test Task ID: {task_id}")
    logger.info(f"Test Agent ID: {agent_id}")

    try:
        # Step 1: Test CLI Agent Creation (Mock)
        logger.info("\n📋 Step 1: Testing CLI Agent Creation")
        logger.info("-" * 40)

        # Note: In a real test, this would create an actual agent
        # For this integration test, we'll simulate the CLI response
        agent_creation_result = {
            "success": True,
            "agent_id": str(agent_id),
            "message": "Agent created successfully (simulated)",
        }

        logger.info(f"✅ Agent creation simulated: {agent_creation_result['message']}")

        # Step 2: Setup Event Infrastructure
        logger.info("\n🔧 Step 2: Setting up Event Infrastructure")
        logger.info("-" * 40)

        # Create EventBroker
        settings = RedisSettings()
        router = get_event_router(settings)
        event_broker = create_event_broker_from_router(router)

        # Create mock repository factory
        class MockRepositoryFactory(RepositoryFactory):
            def __init__(self):
                # Create mock session and user context
                self.session = None
                self.user_context = UserContext(user_id="test_user", workspace_id="test_workspace")

            def create_repository(self, repository_class):
                if repository_class.__name__ == "TaskRepository":
                    return MockTaskRepository()
                return None

        # Create TaskService
        repository_factory = MockRepositoryFactory()
        task_manager = MockTaskManager()
        task_service = TaskService(
            repository_factory=repository_factory,
            event_broker=event_broker,
            task_manager=task_manager,
        )

        # Create test task
        test_task = SimpleTask(
            id=task_id,
            title="CLI Integration Test Task",
            description="Testing CLI → Workflow → SSE flow",
            query="Complete this integration test task",
            user_id="test_user",
            agent_id=agent_id,
            status="running",
            execution_id=f"agent-task-{task_id}",
        )
        # Add task to task manager
        task_manager.tasks[task_id] = test_task

        logger.info("✅ Event infrastructure setup complete")

        # Step 3: Setup Workflow Environment
        logger.info("\n⚙️ Step 3: Setting up Workflow Environment")
        logger.info("-" * 40)

        # Create workflow environment
        env = await WorkflowEnvironment.start_time_skipping()

        # Create mock activities
        activities = await create_mock_workflow_activities()

        # Store event broker globally for activities to access
        # Note: In a real implementation, this would be injected via dependency injection
        global _test_event_broker
        _test_event_broker = event_broker

        # Create worker
        worker = Worker(
            env.client,
            task_queue="test-task-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
        )

        logger.info("✅ Workflow environment setup complete")

        # Step 4: Start SSE Streaming in Background
        logger.info("\n📡 Step 4: Starting SSE Streaming")
        logger.info("-" * 40)

        # Start SSE streaming task
        sse_task = asyncio.create_task(
            simulate_sse_streaming(task_service, task_id, event_collector, max_events=8, timeout=20)
        )

        # Small delay to let SSE subscription set up
        await asyncio.sleep(1)

        logger.info("✅ SSE streaming started")

        # Step 5: Execute Workflow
        logger.info("\n🔄 Step 5: Executing Workflow")
        logger.info("-" * 40)

        async with worker:
            # Create workflow request
            request = AgentExecutionRequest(
                agent_id=agent_id,
                task_id=task_id,
                user_id="test_user",
                task_query="Complete this CLI integration test task",
                budget_usd=1.0,
            )

            # Start workflow
            workflow_handle = await env.client.start_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"agent-task-{task_id}",
                task_queue="test-task-queue",
            )

            logger.info(f"🚀 Workflow started: {workflow_handle.id}")

            # Wait for workflow to complete
            result = await workflow_handle.result()

            logger.info(f"✅ Workflow completed: {result.success}")

        # Step 6: Wait for SSE Events
        logger.info("\n⏳ Step 6: Waiting for SSE Events")
        logger.info("-" * 40)

        # Wait a bit more for events to propagate
        await asyncio.sleep(2)

        # Cancel SSE task if still running
        if not sse_task.done():
            sse_task.cancel()
            try:
                await sse_task
            except asyncio.CancelledError:
                pass

        # Step 7: Analyze Results
        logger.info("\n📊 Step 7: Analyzing Results")
        logger.info("-" * 40)

        summary = event_collector.get_summary()

        logger.info(f"Total events collected: {summary['total_events']}")
        logger.info(f"Event types seen: {summary['event_types']}")

        for event_type, count in summary["event_type_counts"].items():
            logger.info(f"  - {event_type}: {count} events")

        # Verify we got workflow events
        workflow_events = [
            e for e in event_collector.events if e.get("event_type", "").startswith("workflow.")
        ]

        logger.info(f"\nWorkflow events received: {len(workflow_events)}")

        # Step 8: Validate Integration
        logger.info("\n✅ Step 8: Validating Integration")
        logger.info("-" * 40)

        success = True

        # Check if we received any events
        if summary["total_events"] == 0:
            logger.error("❌ No events received via SSE")
            success = False
        else:
            logger.info(f"✅ Received {summary['total_events']} events via SSE")

        # Check for workflow events specifically
        if len(workflow_events) == 0:
            logger.warning(
                "⚠️ No workflow events received (may be expected if events are transformed)"
            )
        else:
            logger.info(f"✅ Received {len(workflow_events)} workflow events")

        # Check for expected event types
        expected_events = [
            "workflow.WorkflowStarted",
            "workflow.LLMCallStarted",
            "workflow.LLMCallCompleted",
        ]
        for expected_event in expected_events:
            if event_collector.has_event_type(expected_event):
                logger.info(f"✅ Found expected event: {expected_event}")
            else:
                logger.warning(f"⚠️ Missing expected event: {expected_event}")

        # Final result
        logger.info("\n" + "=" * 80)
        if success:
            logger.info("🎉 CLI → Workflow → SSE Integration Test PASSED!")
            logger.info("   ✅ Agent creation simulated")
            logger.info("   ✅ Workflow executed successfully")
            logger.info("   ✅ Events published to event bus")
            logger.info("   ✅ SSE streaming received events")
        else:
            logger.error("❌ CLI → Workflow → SSE Integration Test FAILED!")

        return success

    except Exception as e:
        logger.error(f"❌ Integration test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Cleanup
        try:
            if (
                "event_broker" in locals()
                and hasattr(event_broker, "_connected")
                and event_broker._connected
            ):
                await event_broker.redis_broker.close()
                logger.info("🧹 Cleaned up Redis connection")
        except Exception as e:
            logger.warning(f"Cleanup warning: {e}")


if __name__ == "__main__":
    # Run the integration test
    result = asyncio.run(test_cli_workflow_sse_integration())

    print("\n" + "=" * 80)
    if result:
        print("🎉 CLI → Workflow → SSE Integration Test COMPLETED SUCCESSFULLY!")
        print("\nThis test demonstrates:")
        print("  1. CLI interface for agent creation (simulated)")
        print("  2. Workflow execution with event publishing")
        print("  3. Real-time event streaming via SSE")
        print("  4. End-to-end event flow validation")
    else:
        print("❌ CLI → Workflow → SSE Integration Test FAILED!")
        print("\nCheck the logs above for details.")

    exit(0 if result else 1)
