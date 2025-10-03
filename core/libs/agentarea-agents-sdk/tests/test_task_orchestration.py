"""Integration test for agentic network task orchestration with task management system.

This test simulates a realistic scenario where a main agent decomposes a complex task,
delegates to specialized agents, tracks progress using the task management system,
and determines if the initial goal is completed.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest

from agentarea_agents_sdk.agents.event_agent import EventAgent
from agentarea_agents_sdk.models.llm_model import LLMRequest, LLMResponse, LLMUsage
from agentarea_agents_sdk.tasks.task_service import InMemoryTaskService
from agentarea_agents_sdk.tools.decorator_tool import ToolsetAdapter
from agentarea_agents_sdk.tools.handoff_tool import AgentHandoffTool
from agentarea_agents_sdk.tools.tasks_toolset import TasksToolset

logger = logging.getLogger(__name__)


@dataclass
class ScriptedResponse:
    """Predefined response for FakeLLM."""

    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    streaming_chunks: list[str] | None = None


class FakeLLMModel:
    """Fake LLM model that returns scripted responses based on message patterns."""

    def __init__(self, provider_type: str = "fake", model_name: str = "test"):
        self.provider_type = provider_type
        self.model_name = model_name
        self.response_queue: list[ScriptedResponse] = []
        self.call_count = 0

    def add_response(self, response: ScriptedResponse) -> None:
        """Add a scripted response to the queue."""
        self.response_queue.append(response)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Complete method - not used in streaming tests but kept for compatibility."""
        response = self._get_next_response(request)
        return LLMResponse(
            content=response.content,
            role="assistant",
            tool_calls=response.tool_calls,
            usage=LLMUsage(prompt_tokens=50, completion_tokens=100, total_tokens=150),
            cost=0.001,
        )

    async def ainvoke_stream(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """Stream LLM responses, yielding chunks and final tool calls."""
        self.call_count += 1
        response = self._get_next_response(request)

        # Yield content chunks if available
        if response.streaming_chunks:
            for chunk in response.streaming_chunks:
                yield LLMResponse(
                    content=chunk, role="assistant", tool_calls=None, usage=None, cost=0.0
                )
        elif response.content:
            # Split content into chunks for realistic streaming
            words = response.content.split()
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield LLMResponse(
                    content=chunk, role="assistant", tool_calls=None, usage=None, cost=0.0
                )

        # Yield final response with tool calls
        if response.tool_calls:
            yield LLMResponse(
                content="",
                role="assistant",
                tool_calls=response.tool_calls,
                usage=LLMUsage(prompt_tokens=50, completion_tokens=100, total_tokens=150),
                cost=0.001,
            )

    def _get_next_response(self, request: LLMRequest) -> ScriptedResponse:
        """Get the next scripted response based on request context."""
        if not self.response_queue:
            # Fallback response
            return ScriptedResponse(content="I understand the task.")

        return self.response_queue.pop(0)


class TestTaskOrchestration:
    """Test multi-agent task orchestration with realistic delegation flow."""

    def setup_method(self):
        """Setup shared task service for all agents."""
        self.shared_task_service = InMemoryTaskService()
        self.agent_results = {}  # Store results from completed agents
        self.handoff_log = []  # Track handoff operations

    @pytest.mark.asyncio
    async def test_full_orchestration_flow(self):
        """Test end-to-end orchestration: main agent → delegation → task tracking → completion."""

        # 🏗️ SETUP: Create specialized agents with task management
        research_agent = self._create_research_agent()
        analysis_agent = self._create_analysis_agent()
        reporting_agent = self._create_reporting_agent()

        # Main orchestrator agent with all tools
        main_agent = self._create_main_orchestrator_agent(
            {
                "research_agent": {
                    "name": "Research Agent",
                    "description": "Gathers market data and competitor analysis",
                    "capabilities": ["market_research", "data_collection"],
                },
                "analysis_agent": {
                    "name": "Analysis Agent",
                    "description": "Analyzes data and identifies trends",
                    "capabilities": ["data_analysis", "pattern_recognition"],
                },
                "reporting_agent": {
                    "name": "Reporting Agent",
                    "description": "Creates comprehensive reports and summaries",
                    "capabilities": ["report_generation", "documentation"],
                },
            }
        )

        # 📋 SCENARIO: Market analysis project
        initial_goal = "Analyze the competitive landscape for electric vehicles in Europe and provide strategic recommendations"

        logger.info("🚀 Starting multi-agent orchestration test")
        logger.info(f"📋 Goal: {initial_goal}")

        # 🎭 ACT: Execute the orchestration
        await self._simulate_orchestration_flow(
            main_agent, research_agent, analysis_agent, reporting_agent, initial_goal
        )

        # 🔍 VERIFY: Check that the orchestration worked correctly
        await self._verify_orchestration_results()

    def _create_main_orchestrator_agent(self, available_agents: dict) -> EventAgent:
        """Create the main orchestrator agent with handoff and task management tools."""
        fake_llm = FakeLLMModel()

        # Script responses for main agent orchestration flow
        fake_llm.add_response(
            ScriptedResponse(
                content="I'll break this market analysis into three key phases:",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "tasks",
                            "arguments": '{"action": "create_task", "title": "European EV Market Analysis", "description": "Comprehensive analysis of competitive landscape for electric vehicles in Europe", "priority": 3}',
                        },
                    }
                ],
            )
        )

        fake_llm.add_response(
            ScriptedResponse(
                content="Now I'll create the research subtask and delegate to the research agent:",
                tool_calls=[
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "tasks",
                            "arguments": '{"action": "add_subtask", "parent_id": "TASK_ID_PLACEHOLDER", "title": "Market Data Collection", "description": "Gather EV sales data, manufacturer info, and regulatory landscape for Europe", "priority": 3}',
                        },
                    }
                ],
            )
        )

        fake_llm.add_response(
            ScriptedResponse(
                content="I'll now hand off the research subtask to our research agent:",
                tool_calls=[
                    {
                        "id": "call_3",
                        "type": "function",
                        "function": {
                            "name": "handoff_to_agent",
                            "arguments": '{"target_agent_id": "research_agent", "handoff_reason": "Specialized in market research", "task_context": "Research EV market in Europe", "expected_deliverable": "Market research report"}',
                        },
                    }
                ],
            )
        )

        # Response after research completion
        fake_llm.add_response(
            ScriptedResponse(
                content="Research completed. Creating analysis subtask:",
                tool_calls=[
                    {
                        "id": "call_4",
                        "type": "function",
                        "function": {
                            "name": "tasks",
                            "arguments": '{"action": "add_subtask", "parent_id": "TASK_ID_PLACEHOLDER", "title": "Data Analysis & Trends", "description": "Analyze collected market data to identify trends and competitive positioning", "priority": 3}',
                        },
                    }
                ],
            )
        )

        fake_llm.add_response(
            ScriptedResponse(
                content="Delegating analysis to specialist:",
                tool_calls=[
                    {
                        "id": "call_5",
                        "type": "function",
                        "function": {
                            "name": "handoff_to_agent",
                            "arguments": '{"target_agent_id": "analysis_agent", "handoff_reason": "Expert in data analysis and trend identification", "task_context": "Analyze European EV market data to identify competitive patterns, market leaders, and growth trends", "expected_deliverable": "Data analysis report with key findings and insights"}',
                        },
                    }
                ],
            )
        )

        # Final reporting phase
        fake_llm.add_response(
            ScriptedResponse(
                content="Creating final reporting subtask:",
                tool_calls=[
                    {
                        "id": "call_6",
                        "type": "function",
                        "function": {
                            "name": "tasks",
                            "arguments": '{"action": "add_subtask", "parent_id": "TASK_ID_PLACEHOLDER", "title": "Strategic Report Generation", "description": "Create comprehensive report with strategic recommendations", "priority": 3}',
                        },
                    }
                ],
            )
        )

        fake_llm.add_response(
            ScriptedResponse(
                content="Delegating report generation:",
                tool_calls=[
                    {
                        "id": "call_7",
                        "type": "function",
                        "function": {
                            "name": "handoff_to_agent",
                            "arguments": '{"target_agent_id": "reporting_agent", "handoff_reason": "Specialized in creating comprehensive strategic reports", "task_context": "Generate final strategic recommendations report based on research and analysis findings", "expected_deliverable": "Executive report with strategic recommendations for EV market entry"}',
                        },
                    }
                ],
            )
        )

        # Final completion
        fake_llm.add_response(
            ScriptedResponse(
                content="All agents have completed their tasks. The European EV market analysis is complete with strategic recommendations ready.",
                tool_calls=[
                    {
                        "id": "call_8",
                        "type": "function",
                        "function": {
                            "name": "completion",
                            "arguments": '{"result": "Successfully completed comprehensive European EV market analysis with strategic recommendations from research, analysis, and reporting specialists"}',
                        },
                    }
                ],
            )
        )

        # Create tools
        tasks_toolset = ToolsetAdapter(TasksToolset(self.shared_task_service))
        handoff_tool = AgentHandoffTool(available_agents, self._handle_agent_handoff)

        return EventAgent(
            name="Market Analysis Orchestrator",
            instruction="You are a project manager specializing in market analysis. Break down complex tasks into subtasks, delegate to specialist agents, and track progress using the task management system.",
            llm_executor=fake_llm,
            tools=[tasks_toolset, handoff_tool],
            include_default_tools=True,  # Includes completion tool
            event_listener=self._log_orchestrator_events,
        )

    def _create_research_agent(self) -> EventAgent:
        """Create research specialist agent."""
        fake_llm = FakeLLMModel()

        fake_llm.add_response(
            ScriptedResponse(
                content="I'll conduct comprehensive research on the European EV market. Let me start by setting up my research tasks:",
                tool_calls=[
                    {
                        "id": "research_1",
                        "type": "function",
                        "function": {
                            "name": "tasks",
                            "arguments": '{"action": "create_task", "title": "EV Sales Data Collection", "description": "Gather 2023-2024 EV sales figures for major European markets", "priority": 2}',
                        },
                    }
                ],
            )
        )

        fake_llm.add_response(
            ScriptedResponse(
                content="Research completed successfully. I've gathered comprehensive EV market data including sales figures from Germany, France, Norway, and UK, plus regulatory landscape analysis.",
                tool_calls=[
                    {
                        "id": "research_2",
                        "type": "function",
                        "function": {
                            "name": "completion",
                            "arguments": '{"result": "European EV market research complete: Sales data shows Norway leading at 80% EV adoption, Germany growing 35% YoY, regulatory support strong across EU with 2035 ICE ban driving adoption"}',
                        },
                    }
                ],
            )
        )

        tasks_toolset = ToolsetAdapter(TasksToolset(self.shared_task_service))

        return EventAgent(
            name="Market Research Specialist",
            instruction="You are an expert market researcher specializing in automotive industry data collection and analysis.",
            llm_executor=fake_llm,
            tools=[tasks_toolset],
            include_default_tools=True,
            event_listener=self._log_agent_events("research"),
        )

    def _create_analysis_agent(self) -> EventAgent:
        """Create analysis specialist agent."""
        fake_llm = FakeLLMModel()

        fake_llm.add_response(
            ScriptedResponse(
                content="I'll analyze the collected market data to identify key trends and competitive patterns:",
                tool_calls=[
                    {
                        "id": "analysis_1",
                        "type": "function",
                        "function": {
                            "name": "tasks",
                            "arguments": '{"action": "create_task", "title": "Competitive Positioning Analysis", "description": "Analyze market share and positioning of major EV manufacturers", "priority": 2}',
                        },
                    }
                ],
            )
        )

        fake_llm.add_response(
            ScriptedResponse(
                content="Analysis complete. Key findings: Tesla maintains premium segment leadership but VW Group is rapidly gaining market share in mass market. Chinese manufacturers like BYD are entering European market aggressively.",
                tool_calls=[
                    {
                        "id": "analysis_2",
                        "type": "function",
                        "function": {
                            "name": "completion",
                            "arguments": '{"result": "EV market analysis complete: Tesla leads premium (25% market share), VW Group dominates mass market (18%), Chinese manufacturers gaining ground. Key trend: Rapid charging infrastructure expansion driving adoption"}',
                        },
                    }
                ],
            )
        )

        tasks_toolset = ToolsetAdapter(TasksToolset(self.shared_task_service))

        return EventAgent(
            name="Data Analysis Specialist",
            instruction="You are an expert data analyst specializing in automotive market trends and competitive intelligence.",
            llm_executor=fake_llm,
            tools=[tasks_toolset],
            include_default_tools=True,
            event_listener=self._log_agent_events("analysis"),
        )

    def _create_reporting_agent(self) -> EventAgent:
        """Create reporting specialist agent."""
        fake_llm = FakeLLMModel()

        fake_llm.add_response(
            ScriptedResponse(
                content="I'll create a comprehensive strategic report based on the research and analysis findings:",
                tool_calls=[
                    {
                        "id": "report_1",
                        "type": "function",
                        "function": {
                            "name": "tasks",
                            "arguments": '{"action": "create_task", "title": "Executive Summary Creation", "description": "Create executive summary with key recommendations", "priority": 3}',
                        },
                    }
                ],
            )
        )

        fake_llm.add_response(
            ScriptedResponse(
                content="Strategic report completed. Recommendations: 1) Target mass market segment to compete with VW Group, 2) Establish charging partnerships to accelerate adoption, 3) Focus on Germany/France markets with highest growth potential, 4) Monitor Chinese competition closely.",
                tool_calls=[
                    {
                        "id": "report_2",
                        "type": "function",
                        "function": {
                            "name": "completion",
                            "arguments": '{"result": "Strategic EV market entry report complete with 4 key recommendations: mass market focus, charging partnerships, Germany/France targeting, and competitive monitoring strategy"}',
                        },
                    }
                ],
            )
        )

        tasks_toolset = ToolsetAdapter(TasksToolset(self.shared_task_service))

        return EventAgent(
            name="Strategic Reporting Specialist",
            instruction="You are an expert business strategist specializing in creating comprehensive market entry reports and strategic recommendations.",
            llm_executor=fake_llm,
            tools=[tasks_toolset],
            include_default_tools=True,
            event_listener=self._log_agent_events("reporting"),
        )

    async def _handle_agent_handoff(self, handoff_payload: dict[str, Any]) -> dict[str, Any]:
        """Handle agent handoff by executing the target agent."""
        target_agent_id = handoff_payload["target_agent_id"]
        task_context = handoff_payload["task_context"]

        self.handoff_log.append(
            {"target": target_agent_id, "context": task_context, "timestamp": "2024-01-01T10:00:00"}
        )

        logger.info(f"🔄 Handoff to {target_agent_id}: {task_context}")

        # Simulate agent execution (in real scenario, this would invoke the target agent)
        # For testing, we'll just record that the handoff happened
        return {
            "handoff_executed": True,
            "target_agent": target_agent_id,
            "execution_id": str(uuid4()),
        }

    def _log_orchestrator_events(self, event):
        """Log orchestrator events."""
        logger.info(f"🎯 ORCHESTRATOR EVENT: {event.type} - {event.payload}")

    def _log_agent_events(self, agent_type: str):
        """Create event logger for specific agent type."""

        def logger_func(event):
            logger.info(f"🤖 {agent_type.upper()} AGENT EVENT: {event.type} - {event.payload}")

        return logger_func

    async def _simulate_orchestration_flow(
        self,
        main_agent: EventAgent,
        research_agent: EventAgent,
        analysis_agent: EventAgent,
        reporting_agent: EventAgent,
        goal: str,
    ):
        """Simulate the complete orchestration flow."""

        logger.info("=" * 60)
        logger.info("🎬 PHASE 1: Main agent orchestration and task breakdown")
        logger.info("=" * 60)

        # Run main agent to set up tasks and delegate
        response_parts = []
        async for chunk in main_agent.run_stream(goal):
            response_parts.append(chunk)

        main_response = "".join(response_parts)
        logger.info(f"📋 Main agent response: {main_response[:200]}...")

        # Verify tasks were created
        root_tasks = self.shared_task_service.find_roots()
        assert len(root_tasks) > 0, "Main agent should create at least one root task"

        main_task = root_tasks[0]
        logger.info(f"✅ Created main task: {main_task.title}")

        # Check subtasks were created
        subtasks = list(self.shared_task_service.list_subtasks(main_task.id))
        assert len(subtasks) >= 2, "Should create multiple subtasks for delegation"

        logger.info(f"✅ Created {len(subtasks)} subtasks")
        for subtask in subtasks:
            logger.info(f"   - {subtask.title}: {subtask.description}")

        # Verify handoffs occurred
        assert len(self.handoff_log) >= 2, "Should perform multiple agent handoffs"
        logger.info(f"✅ Performed {len(self.handoff_log)} agent handoffs")

        logger.info("\n" + "=" * 60)
        logger.info("🎬 PHASE 2: Specialized agent execution")
        logger.info("=" * 60)

        # Simulate execution of specialized agents
        await self._execute_specialized_agents(research_agent, analysis_agent, reporting_agent)

        logger.info("\n" + "=" * 60)
        logger.info("🎬 PHASE 3: Final orchestration and completion")
        logger.info("=" * 60)

        # Continue main agent execution to complete orchestration
        final_response_parts = []
        async for chunk in main_agent.run_stream(
            "All specialized agents have completed their tasks. Please review results and complete the project."
        ):
            final_response_parts.append(chunk)

        final_response = "".join(final_response_parts)
        logger.info(f"🎯 Final orchestration: {final_response[:200]}...")

    async def _execute_specialized_agents(
        self, research_agent: EventAgent, analysis_agent: EventAgent, reporting_agent: EventAgent
    ):
        """Execute the specialized agents in sequence."""

        # Execute research agent
        logger.info("🔬 Executing research agent...")
        research_parts = []
        async for chunk in research_agent.run_stream(
            "Conduct comprehensive European EV market research as requested"
        ):
            research_parts.append(chunk)

        research_result = "".join(research_parts)
        self.agent_results["research"] = research_result
        logger.info(f"✅ Research completed: {research_result[:200]}...")

        # Execute analysis agent
        logger.info("📊 Executing analysis agent...")
        analysis_parts = []
        async for chunk in analysis_agent.run_stream(
            "Analyze the EV market research data and identify key trends"
        ):
            analysis_parts.append(chunk)

        analysis_result = "".join(analysis_parts)
        self.agent_results["analysis"] = analysis_result
        logger.info(f"✅ Analysis completed: {analysis_result[:200]}...")

        # Execute reporting agent
        logger.info("📝 Executing reporting agent...")
        report_parts = []
        async for chunk in reporting_agent.run_stream(
            "Create strategic recommendations report based on research and analysis"
        ):
            report_parts.append(chunk)

        report_result = "".join(report_parts)
        self.agent_results["reporting"] = report_result
        logger.info(f"✅ Reporting completed: {report_result[:200]}...")

    async def _verify_orchestration_results(self):
        """Verify the orchestration produced expected results."""

        logger.info("\n" + "=" * 60)
        logger.info("🔍 VERIFICATION: Checking orchestration results")
        logger.info("=" * 60)

        # Check task management system was used properly
        all_tasks = self.shared_task_service.dump()
        logger.info(f"📊 Total tasks created: {len(all_tasks)}")

        root_tasks = self.shared_task_service.find_roots()
        assert len(root_tasks) >= 1, "Should have at least one root task"

        main_task = root_tasks[0]
        subtasks = list(self.shared_task_service.list_subtasks(main_task.id))

        logger.info(f"✅ Task hierarchy: 1 root task with {len(subtasks)} subtasks")

        # Check that handoffs occurred
        assert len(self.handoff_log) >= 3, (
            f"Expected at least 3 handoffs, got {len(self.handoff_log)}"
        )
        logger.info(f"✅ Agent handoffs: {len(self.handoff_log)} successful delegations")

        for i, handoff in enumerate(self.handoff_log, 1):
            logger.info(f"   {i}. {handoff['target']}: {handoff['context'][:100]}...")

        # Check that all agents produced results
        expected_agents = ["research", "analysis", "reporting"]
        for agent_type in expected_agents:
            assert agent_type in self.agent_results, f"Missing results from {agent_type} agent"
            assert len(self.agent_results[agent_type]) > 50, f"{agent_type} agent result too short"

        logger.info(
            f"✅ Agent results: All {len(expected_agents)} agents produced substantial outputs"
        )

        # Verify goal completion indicators
        final_tasks = [
            t
            for t in all_tasks
            if "Strategic" in t.get("title", "") or "complete" in t.get("description", "").lower()
        ]
        assert len(final_tasks) > 0, "Should have completion-related tasks"

        logger.info("✅ Goal completion: Evidence of strategic recommendations and completion")

        logger.info(
            "\n🎉 ORCHESTRATION TEST PASSED: Multi-agent task delegation with task management successful!"
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
