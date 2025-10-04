"""Test real workflow with real activities but mocked database infrastructure."""

import logging
import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


class MockedInfrastructureDependencies:
    """Dependencies with mocked database but real LLM calls."""

    class MockSecretManager:
        async def get_secret(self, secret_name: str) -> str:
            # Return empty for Ollama (no API key needed)
            return ""

    class MockEventBroker:
        def __init__(self):
            self.published_events = []
            self.broker = self  # Add broker attribute

        async def publish(self, event):
            self.published_events.append(event)
            logger.debug(f"Mock event published: {getattr(event, 'event_type', 'unknown')}")

    def __init__(self):
        self.secret_manager = self.MockSecretManager()
        self.event_broker = self.MockEventBroker()


@pytest.mark.asyncio
async def test_real_workflow_with_mocked_infrastructure():
    """Test real workflow using real activities but with mocked database infrastructure."""

    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")

    # Create dependencies with mocked infrastructure
    dependencies = MockedInfrastructureDependencies()

    # Create real activities
    activities = make_agent_activities(dependencies)

    # We need to patch the activities that require database access
    # Let's create custom activities that return test data

    from temporalio import activity

    # Test data that matches what would be in the database
    test_agent_config = {
        "id": "12345678-1234-5678-1234-567812345678",
        "name": "Test Agent",
        "description": "Agent for testing malformed responses",
        "instruction": "You are Test Agent, an AI agent that follows the ReAct (Reasoning + Acting) framework.\n\nComplete tasks efficiently\n\n## Current Task\nGoal: test\n\nSuccess Criteria:\n- Task completed successfully\n\n## Available Tools\n- task_complete: Mark task as completed\n- task_complete: Mark the task as completed when all success criteria are met\n\n## ReAct Framework Instructions\nYou MUST follow this exact pattern for EVERY action you take:\n\n1. **Thought**: First, analyze the current situation and what needs to be done\n2. **Observation**: Note what information you have and what you're missing  \n3. **Action**: Decide on the next action (tool call or response)\n4. **Result**: After a tool call, observe and interpret the results\n\nFor each step, explicitly state your reasoning process using these markers:\n\n**Thought:** [Your reasoning about the current situation]\n**Observation:** [What you observe from previous results or current context]\n**Action:** [What action you decide to take and why]\n\nAfter receiving tool results, always provide:\n**Result Analysis:** [Interpretation of the tool results and what they mean]\n\nExample flow:\n**Thought:** I need to search for information about X to complete the task.\n**Observation:** I don't have current information about X in my knowledge.\n**Action:** I'll use the web_search tool to find recent information.\n[Tool call happens]\n**Result Analysis:** The search returned Y, which shows that...\n**Thought:** Now that I have Y, I need to...\n\nCRITICAL RULES:\n- NEVER call tools without first showing your **Thought** and **Observation**\n- NEVER call task_complete without first demonstrating your work step-by-step\n- You must show your reasoning process for EVERY action, including the final completion\n- The task_complete tool requires detailed summary, reasoning, and result - prepare these thoughtfully\n\nContinue this pattern until the task is complete, then use the task_complete tool with comprehensive details.\n\nRemember: ALWAYS show your reasoning before taking actions. Users want to see your thought process.",
        "model_id": "66666666-6666-6666-6666-666666666666",
        "tools_config": {},
        "events_config": {},
        "planning": False,
    }

    test_tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark task as completed when you have finished the task successfully. Call this when you're done.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Optional final result or summary of what was accomplished",
                        }
                    },
                    "required": [],
                },
            },
        }
    ]

    # Mock the database-dependent activities
    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(agent_id: UUID, user_context_data: dict, **kwargs):
        logger.info(f"Mock: Building agent config for {agent_id}")
        return test_agent_config

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(agent_id: UUID, user_context_data: dict, **kwargs):
        logger.info(f"Mock: Discovering tools for {agent_id}")
        return test_tools

    # Create a custom LLM activity that uses real Ollama but with proper model configuration
    @activity.defn(name="call_llm_activity")
    async def real_llm_with_ollama(
        messages,
        model_id,
        tools=None,
        workspace_id=None,
        user_context_data=None,
        temperature=None,
        max_tokens=None,
        task_id=None,
        agent_id=None,
        execution_id=None,
    ):
        logger.info("🚀 Real LLM call with Ollama (mocked model instance)")
        logger.info(f"📝 Messages: {len(messages)} messages")
        logger.info(f"🔧 Tools: {len(tools) if tools else 0} tools")
        logger.info(f"🎯 Model ID: {model_id} (will use Ollama qwen2.5)")

        from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

        # Use real Ollama with a model that supports tool calling
        llm_model = LLMModel(
            provider_type="ollama_chat",
            model_name="llama3.1",  # Use a model that supports tool calling
            endpoint_url=f"http://{docker_host}:11434",
        )

        request = LLMRequest(
            messages=messages,
            tools=tools,
            temperature=temperature or 0.1,
            max_tokens=max_tokens or 300,
        )

        try:
            # Use streaming to match production behavior exactly
            complete_content = ""
            complete_tool_calls = None
            final_usage = None
            final_cost = 0.0
            chunk_count = 0

            logger.info("📡 Starting streaming LLM call...")
            async for chunk in llm_model.ainvoke_stream(request):
                chunk_count += 1

                if chunk.content:
                    complete_content += chunk.content
                    if (
                        chunk_count <= 5 or chunk_count % 20 == 0
                    ):  # Log first few and every 20th chunk
                        logger.debug(
                            f"📝 Chunk {chunk_count}: '{chunk.content[:30]}{'...' if len(chunk.content) > 30 else ''}'"
                        )

                if chunk.tool_calls:
                    complete_tool_calls = chunk.tool_calls
                    logger.info(
                        f"🔧 Tool calls received in chunk {chunk_count}: {chunk.tool_calls}"
                    )

                if chunk.usage:
                    final_usage = chunk.usage

                if chunk.cost:
                    final_cost = chunk.cost

            # Create final response in the format expected by workflow
            result = {
                "role": "assistant",
                "content": complete_content,
                "tool_calls": complete_tool_calls,
                "cost": final_cost,
                "usage": final_usage.__dict__ if final_usage else None,
            }

            logger.info("=" * 60)
            logger.info("🎯 FINAL LLM RESPONSE ANALYSIS")
            logger.info("=" * 60)
            logger.info(f"📊 Total chunks: {chunk_count}")
            logger.info(f"📝 Content length: {len(complete_content)} chars")
            logger.info(f"🔧 Tool calls: {complete_tool_calls}")
            logger.info(f"💰 Cost: ${final_cost:.6f}")

            # Check for malformed response pattern
            if not complete_tool_calls and complete_content:
                if "task_complete" in complete_content.lower():
                    logger.warning("🚨 MALFORMED RESPONSE DETECTED!")
                    logger.warning("Tool calls are None but content mentions task_complete")
                    logger.warning(f"Content preview: {complete_content[:200]}...")

                    # Try to extract JSON patterns
                    import re

                    json_patterns = [
                        r'\{\s*"name"\s*:\s*"task_complete"[^}]*\}',
                        r'\{\s*"name"\s*:\s*"task_complete"[^}]*"arguments"[^}]*\}',
                    ]

                    for pattern in json_patterns:
                        matches = re.findall(pattern, complete_content, re.DOTALL)
                        if matches:
                            logger.warning(f"🔍 Found JSON pattern: {matches[0]}")
                            break
                else:
                    logger.info("✅ Response format appears correct (no tool calls expected)")
            else:
                logger.info("✅ Response format is CORRECT - tool calls properly returned")

            logger.info("=" * 60)

            return result

        except Exception as e:
            logger.error(f"❌ Real LLM call failed: {e}")
            raise

    # Keep other real activities but replace database-dependent ones
    real_activities = []
    for activity_func in activities:
        activity_name = getattr(activity_func, "__name__", "")
        if "build_agent_config" in activity_name:
            real_activities.append(mock_build_agent_config)
        elif "discover_available_tools" in activity_name:
            real_activities.append(mock_discover_tools)
        elif "call_llm" in activity_name:
            real_activities.append(real_llm_with_ollama)
        else:
            real_activities.append(activity_func)

    # Create execution request
    execution_request = AgentExecutionRequest(
        agent_id="12345678-1234-5678-1234-567812345678",
        task_id=uuid4(),
        user_id="22222222-2222-2222-2222-222222222222",
        task_query="test",  # Use the exact same query as production
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 3},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    logger.info("🧪 Testing REAL workflow with REAL LLM but mocked database")
    logger.info(f"🎯 Task: '{execution_request.task_query}'")
    logger.info(f"🤖 Agent ID: {execution_request.agent_id}")
    logger.info(f"📊 Max iterations: {execution_request.task_parameters['max_iterations']}")
    logger.info(f"💰 Budget: ${execution_request.budget_usd}")

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="real-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=real_activities,
            debug_mode=True,  # Disable sandbox for better debugging
        ):
            logger.info("🚀 Starting workflow execution...")

            result = await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"real-test-{uuid4()}",
                task_queue="real-test-queue",
                execution_timeout=timedelta(minutes=3),
            )

            logger.info("=" * 60)
            logger.info("🎉 WORKFLOW EXECUTION COMPLETED!")
            logger.info("=" * 60)
            logger.info(f"✅ Success: {result.success}")
            logger.info(f"📊 Iterations: {result.reasoning_iterations_used}")
            logger.info(f"💬 Final response: {result.final_response}")
            logger.info(f"💰 Total cost: ${result.total_cost:.6f}")
            logger.info(f"📝 Conversation messages: {len(result.conversation_history)}")

            # Analyze conversation history for malformed responses
            logger.info("\n🔍 CONVERSATION ANALYSIS:")
            malformed_detected = False

            for i, msg in enumerate(result.conversation_history):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")

                if role == "assistant":
                    logger.info(
                        f"📝 Message {i} (assistant): {len(content)} chars, tool_calls: {bool(tool_calls)}"
                    )

                    # Check for malformed response pattern
                    if not tool_calls and content and "task_complete" in content.lower():
                        logger.warning(
                            f"🚨 MALFORMED in message {i}: task_complete in content but no tool_calls"
                        )
                        logger.warning(f"Content: {content[:100]}...")
                        malformed_detected = True
                    elif tool_calls:
                        logger.info(f"✅ Message {i}: Proper tool calls detected")

            # Final assessment
            logger.info("\n" + "=" * 60)
            logger.info("🎯 FINAL ASSESSMENT")
            logger.info("=" * 60)

            if malformed_detected:
                logger.error("🚨 MALFORMED RESPONSES DETECTED!")
                logger.error("The issue is confirmed to be in the LLM response processing chain")
                logger.error("This proves the malformed responses are coming from:")
                logger.error("- Ollama/qwen2.5 model behavior")
                logger.error("- litellm processing")
                logger.error("- Our agents SDK streaming")
                logger.error("- Or the workflow tool call extraction")
            else:
                logger.info("✅ NO MALFORMED RESPONSES DETECTED!")
                logger.info("The real LLM infrastructure works correctly")
                logger.info("Production malformed responses must be from:")
                logger.info("- Different model/provider configuration")
                logger.info("- Different environment setup")
                logger.info("- Database configuration issues")

            # Verify workflow completed properly
            if result.success:
                logger.info("🎉 Workflow completed successfully with real LLM!")
                assert result.reasoning_iterations_used >= 1, (
                    "Should have completed at least 1 iteration"
                )
            else:
                logger.warning("⚠️ Workflow did not complete successfully")
                logger.warning(
                    "This might indicate an issue with the LLM responses or tool execution"
                )

            logger.info("=" * 60)

    finally:
        await env.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
