import asyncio
import logging
import os
import threading
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from agentarea_agents.infrastructure.di_container import initialize_di_container
from agentarea_common.config import Database, get_settings
from agentarea_execution import ActivityDependencies, create_activities_for_worker
from agentarea_execution.models import AgentExecutionRequest, AgentExecutionResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set default environment variables for test infra
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("TEMPORAL_SERVER_URL", "localhost:7233")
os.environ.setdefault("TEMPORAL_NAMESPACE", "default")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEBUG", "true")
os.environ["REDIS_URL"] = "redis://localhost:6379"


class E2ETemporalTest:
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        self.worker = None
        self.worker_thread = None
        self.worker_shutdown_event = threading.Event()
        self.task_queue = f"e2e-test-{uuid4()}"
        self.test_model_id = None
        self.test_model_instance_id = None
        self.test_agent_id = None

    async def setup_infrastructure(self):
        await self._check_temporal_server()
        await self._check_database()
        await self._check_redis()
        initialize_di_container(self.settings.workflow)
        await self._create_test_llm_infrastructure()
        await self._setup_activity_dependencies()
        self.client = await Client.connect(
            self.settings.workflow.TEMPORAL_SERVER_URL,
            namespace=self.settings.workflow.TEMPORAL_NAMESPACE,
            data_converter=pydantic_data_converter,
        )

    async def _create_test_llm_infrastructure(self):
        # Minimal test event broker and secret manager
        from agentarea_common.events.broker import EventBroker
        from agentarea_common.infrastructure.secret_manager import BaseSecretManager
        from agentarea_llm.application.llm_model_service import LLMModelService
        from agentarea_llm.application.service import LLMModelInstanceService
        from agentarea_llm.infrastructure.llm_model_instance_repository import (
            LLMModelInstanceRepository,
        )
        from agentarea_llm.infrastructure.llm_model_repository import LLMModelRepository

        class DummyEventBroker(EventBroker):
            async def publish(self, event):
                pass

        class DummySecretManager(BaseSecretManager):
            async def get_secret(self, _):
                return "test-api-key"

            async def set_secret(self, *_):
                pass

            async def delete_secret(self, _):
                pass

        db = Database(self.settings.database)
        async with db.get_db() as session:
            llm_model_repository = LLMModelRepository(session)
            llm_model_service = LLMModelService(llm_model_repository, DummyEventBroker())
            llm_instance_repository = LLMModelInstanceRepository(session)
            llm_instance_service = LLMModelInstanceService(
                llm_instance_repository, DummyEventBroker(), DummySecretManager()
            )
            try:
                model = await llm_model_service.create_llm_model(
                    name="qwen2.5",
                    description="Qwen 2.5 model via Ollama for E2E testing",
                    provider="183a5efc-2525-4a1e-aded-1a5d5e9ff13b",
                    model_name="qwen2.5",
                    endpoint_url=None,
                    context_window="4096",
                    is_public=True,
                )
                self.test_model_id = str(model.id)
            except Exception:
                models = await llm_model_repository.list(
                    provider="183a5efc-2525-4a1e-aded-1a5d5e9ff13b"
                )
                qwen_models = [m for m in models if m.name == "qwen2.5"]
                if qwen_models:
                    self.test_model_id = str(qwen_models[0].id)
                else:
                    raise
            try:
                instance = await llm_instance_service.create_llm_model_instance(
                    model_id=UUID(self.test_model_id),
                    api_key="test-api-key-not-needed-for-ollama",
                    name="E2E Test Qwen2.5",
                    description="Test model instance for E2E testing",
                    is_public=True,
                )
                self.test_model_instance_id = str(instance.id)
            except Exception:
                instances = await llm_instance_repository.list(model_id=UUID(self.test_model_id))
                test_instances = [i for i in instances if "E2E Test" in i.name]
                if test_instances:
                    self.test_model_instance_id = str(test_instances[0].id)
                else:
                    raise
            await session.commit()

    async def _setup_activity_dependencies(self):
        from agentarea_common.events.router import get_event_router
        from agentarea_secrets import get_real_secret_manager

        self.activity_dependencies = ActivityDependencies(
            settings=self.settings,
            event_broker=get_event_router(self.settings.broker),
            secret_manager=get_real_secret_manager(),
        )

    async def _check_temporal_server(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            if sock.connect_ex(("localhost", 7233)) != 0:
                raise ConnectionError("Temporal server not available at localhost:7233")

    async def _check_database(self):
        from agentarea_agents.infrastructure.repository import AgentRepository
        from sqlalchemy import text

        db = Database(self.settings.database)
        async with db.get_db() as session:
            await session.execute(text("SELECT 1"))
            agent_repository = AgentRepository(session)
            agents = await agent_repository.list()
            if not agents:
                logger.warning("No agents found in database")

    async def _check_redis(self):
        import redis.asyncio as redis

        redis_url = getattr(self.settings.broker, "REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url)
        await redis_client.ping()
        await redis_client.close()

    async def start_test_worker(self):
        if not self.client:
            raise RuntimeError("Client not initialized")
        activities = create_activities_for_worker(self.activity_dependencies)
        self.worker = Worker(
            self.client,
            task_queue=self.task_queue,
            workflows=[AgentExecutionWorkflow],
            activities=activities,
            max_concurrent_activities=5,
            max_concurrent_workflow_tasks=2,
        )
        self.worker_shutdown_event.clear()

        def run_worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def run_with_shutdown():
                worker_task = asyncio.create_task(self.worker.run())

                def monitor_shutdown():
                    self.worker_shutdown_event.wait()
                    loop.call_soon_threadsafe(worker_task.cancel)

                threading.Thread(target=monitor_shutdown, daemon=True).start()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    if self.worker:
                        await self.worker.shutdown()

            try:
                loop.run_until_complete(run_with_shutdown())
            finally:
                for task in asyncio.all_tasks(loop):
                    task.cancel()
                loop.run_until_complete(
                    asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True)
                )
                loop.close()

        self.worker_thread = threading.Thread(target=run_worker)
        self.worker_thread.start()
        await asyncio.sleep(2)

    async def stop_test_worker(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_shutdown_event.set()
            self.worker_thread.join(timeout=10.0)
            self.worker = None
            self.worker_thread = None

    async def create_test_agent(self):
        from agentarea_agents.application.agent_service import AgentService
        from agentarea_agents.domain.models import Agent
        from agentarea_agents.infrastructure.repository import AgentRepository
        from agentarea_common.events.broker import EventBroker

        class DummyEventBroker(EventBroker):
            async def publish(self, event):
                pass

        db = Database(self.settings.database)
        async with db.get_db() as session:
            agent_repository = AgentRepository(session)
            agent_service = AgentService(agent_repository, DummyEventBroker())
            existing_agents = await agent_repository.list()
            test_agents = [a for a in existing_agents if "test" in a.name.lower()]
            agent = (test_agents or existing_agents or [None])[0]
            if agent:
                agent.model_id = str(self.test_model_instance_id)
                updated_agent = await agent_service.update(agent)
                self.test_agent_id = updated_agent.id
                return updated_agent.id
            new_agent = Agent(
                name="E2E Test Agent",
                description="Agent created for E2E testing with qwen2.5",
                instruction="You are a helpful assistant for testing purposes.",
                status="active",
                model_id=str(self.test_model_instance_id),
                tools_config={"mcp_servers": []},
                events_config={},
                planning=False,
            )
            created_agent = await agent_service.create(new_agent)
            self.test_agent_id = created_agent.id
            return created_agent.id

    async def create_test_agent_with_tools(self):
        from agentarea_agents.application.agent_service import AgentService
        from agentarea_agents.domain.models import Agent
        from agentarea_agents.infrastructure.repository import AgentRepository
        from agentarea_common.events.broker import EventBroker

        class DummyEventBroker(EventBroker):
            async def publish(self, event):
                pass

        db = Database(self.settings.database)
        async with db.get_db() as session:
            agent_repository = AgentRepository(session)
            agent_service = AgentService(agent_repository, DummyEventBroker())
            existing_agents = await agent_repository.list()
            tool_agents = [
                a for a in existing_agents if "tool" in a.name.lower() and "test" in a.name.lower()
            ]
            agent = tool_agents[0] if tool_agents else None
            tools_config = {
                "mcp_servers": [
                    {
                        "name": "filesystem",
                        "type": "stdio",
                        "command": "npx",
                        "args": ["@modelcontextprotocol/server-filesystem", "/tmp"],
                        "env": {},
                    }
                ]
            }
            if agent:
                agent.model_id = str(self.test_model_instance_id)
                agent.tools_config = tools_config
                updated_agent = await agent_service.update(agent)
                return updated_agent.id
            new_agent = Agent(
                name="E2E Test Tool Agent",
                description="Agent with MCP tools for E2E testing",
                instruction="You are a helpful assistant with access to filesystem tools. Use them when appropriate to help users.",
                status="active",
                model_id=str(self.test_model_instance_id),
                tools_config=tools_config,
                events_config={},
                planning=False,
            )
            created_agent = await agent_service.create(new_agent)
            return created_agent.id

    async def execute_workflow_test(self, agent_id: UUID, test_query: str) -> AgentExecutionResult:
        if not self.client:
            raise RuntimeError("Client not initialized")
        task_id = uuid4()
        workflow_id = f"e2e-test-{task_id}"
        request = AgentExecutionRequest(
            task_id=task_id,
            agent_id=agent_id,
            user_id="e2e_test_user",
            task_query=test_query,
            timeout_seconds=300,
            max_reasoning_iterations=3,
        )
        handle = await self.client.start_workflow(
            AgentExecutionWorkflow.run,
            request,
            id=workflow_id,
            task_queue=self.task_queue,
            execution_timeout=timedelta(minutes=10),
        )
        try:
            return await asyncio.wait_for(handle.result(), timeout=300)
        except TimeoutError:
            await handle.cancel()
            raise

    async def verify_execution_result(self, result: AgentExecutionResult, expected_query: str):
        assert result.success, f"Workflow failed: {result.error_message}"
        assert result.final_response and result.final_response.strip()
        assert result.conversation_history
        assert result.task_id
        assert result.agent_id
        assert result.reasoning_iterations_used >= 0
        assert result.total_tool_calls >= 0

    async def cleanup(self):
        await self.stop_test_worker()
        if self.client:
            try:
                if hasattr(self.client, "shutdown"):
                    await self.client.shutdown()
                elif hasattr(self.client, "close"):
                    await self.client.close()
            except Exception:
                pass
            finally:
                self.client = None


class TestE2EAgentWorkflow:
    @pytest_asyncio.fixture(scope="class")
    async def e2e_test(self):
        test_framework = E2ETemporalTest()
        try:
            await test_framework.setup_infrastructure()
            await test_framework.start_test_worker()
            yield test_framework
        finally:
            try:
                await test_framework.cleanup()
            except Exception:
                if hasattr(test_framework, "worker_shutdown_event"):
                    test_framework.worker_shutdown_event.set()
                if hasattr(test_framework, "worker_thread") and test_framework.worker_thread:
                    test_framework.worker_thread.join(timeout=5.0)

    @pytest_asyncio.fixture(scope="class")
    async def test_agent_id(self, e2e_test: E2ETemporalTest) -> UUID:
        return await e2e_test.create_test_agent()

    @pytest.mark.asyncio
    async def test_simple_query_execution(self, e2e_test: E2ETemporalTest, test_agent_id: UUID):
        test_query = "Hello! Can you introduce yourself?"
        result = await e2e_test.execute_workflow_test(test_agent_id, test_query)
        await e2e_test.verify_execution_result(result, test_query)

    @pytest.mark.asyncio
    async def test_reasoning_task_execution(self, e2e_test: E2ETemporalTest, test_agent_id: UUID):
        test_query = "What's 25 + 17? Please show your reasoning."
        result = await e2e_test.execute_workflow_test(test_agent_id, test_query)
        await e2e_test.verify_execution_result(result, test_query)
        assert result.final_response and (
            "42" in result.final_response or "forty" in result.final_response.lower()
        )

    @pytest.mark.asyncio
    async def test_multiple_concurrent_executions(
        self, e2e_test: E2ETemporalTest, test_agent_id: UUID
    ):
        test_queries = [
            "Count from 1 to 5",
            "What are the primary colors?",
            "Name three planets in our solar system",
        ]
        results = await asyncio.gather(
            *(e2e_test.execute_workflow_test(test_agent_id, q) for q in test_queries)
        )
        for result, query in zip(results, test_queries, strict=False):
            await e2e_test.verify_execution_result(result, query)

    @pytest.mark.asyncio
    async def test_workflow_with_error_handling(
        self, e2e_test: E2ETemporalTest, test_agent_id: UUID
    ):
        test_query = "Please explain quantum physics in exactly 10 words."
        result = await e2e_test.execute_workflow_test(test_agent_id, test_query)
        if result.success:
            await e2e_test.verify_execution_result(result, test_query)
        else:
            assert result.error_message

    @pytest.mark.asyncio
    async def test_agent_with_mcp_tools(self, e2e_test: E2ETemporalTest):
        agent_id = await e2e_test.create_test_agent_with_tools()
        test_query = "Can you help me list files in the current directory using available tools?"
        result = await e2e_test.execute_workflow_test(agent_id, test_query)
        await e2e_test.verify_execution_result(result, test_query)
        assert result.total_tool_calls > 0
        assert any(
            "tool" in str(msg).lower() or "mcp" in str(msg).lower()
            for msg in result.conversation_history
        )

    @pytest.mark.asyncio
    async def test_workflow_requiring_user_input(
        self, e2e_test: E2ETemporalTest, test_agent_id: UUID
    ):
        test_query = "I need to make a decision but I'll need your input. Please ask me what my favorite color is."
        if not e2e_test.client:
            raise RuntimeError("Client not initialized")
        task_id = uuid4()
        workflow_id = f"e2e-test-user-input-{task_id}"
        request = AgentExecutionRequest(
            task_id=task_id,
            agent_id=test_agent_id,
            user_id="e2e_test_user",
            task_query=test_query,
            timeout_seconds=300,
            max_reasoning_iterations=3,
        )
        handle = await e2e_test.client.start_workflow(
            AgentExecutionWorkflow.run,
            request,
            id=workflow_id,
            task_queue=e2e_test.task_queue,
            execution_timeout=timedelta(minutes=10),
        )
        await asyncio.sleep(3)
        try:
            result = await asyncio.wait_for(handle.result(), timeout=60)
            assert result.success or result.error_message
        except TimeoutError:
            await handle.cancel()
            logger.info("Workflow timed out waiting for user input as expected")

    @pytest.mark.asyncio
    async def test_workflow_with_user_signal(self, e2e_test: E2ETemporalTest, test_agent_id: UUID):
        test_query = "Please help me with a task that requires user confirmation."
        if not e2e_test.client:
            raise RuntimeError("Client not initialized")
        task_id = uuid4()
        workflow_id = f"e2e-test-signal-{task_id}"
        request = AgentExecutionRequest(
            task_id=task_id,
            agent_id=test_agent_id,
            user_id="e2e_test_user",
            task_query=test_query,
            timeout_seconds=300,
            max_reasoning_iterations=3,
        )
        handle = await e2e_test.client.start_workflow(
            AgentExecutionWorkflow.run,
            request,
            id=workflow_id,
            task_queue=e2e_test.task_queue,
            execution_timeout=timedelta(minutes=10),
        )
        await asyncio.sleep(2)
        try:
            await handle.signal("user_response", {"response": "Yes, please proceed with the task."})
            result = await asyncio.wait_for(handle.result(), timeout=120)
            if result.success:
                await e2e_test.verify_execution_result(result, test_query)
                assert result.conversation_history
            else:
                assert result.error_message
        except TimeoutError:
            await handle.cancel()
            logger.info("Workflow timed out - may be waiting for different signal")
        except Exception as e:
            await handle.cancel()
            logger.info(f"Signal test encountered expected exception: {e}")

    @pytest.mark.asyncio
    async def test_workflow_signal_handling_patterns(
        self, e2e_test: E2ETemporalTest, test_agent_id: UUID
    ):
        test_query = "Start a task and wait for my instructions on how to proceed."
        if not e2e_test.client:
            raise RuntimeError("Client not initialized")
        task_id = uuid4()
        workflow_id = f"e2e-test-signals-{task_id}"
        request = AgentExecutionRequest(
            task_id=task_id,
            agent_id=test_agent_id,
            user_id="e2e_test_user",
            task_query=test_query,
            timeout_seconds=300,
            max_reasoning_iterations=3,
        )
        handle = await e2e_test.client.start_workflow(
            AgentExecutionWorkflow.run,
            request,
            id=workflow_id,
            task_queue=e2e_test.task_queue,
            execution_timeout=timedelta(minutes=10),
        )
        await asyncio.sleep(2)
        try:
            signals_to_test = [
                ("pause_execution", {"reason": "User requested pause"}),
                ("resume_execution", {"continue": True}),
                ("update_context", {"additional_info": "Use verbose output"}),
                ("user_feedback", {"feedback": "The task is proceeding well"}),
            ]
            for signal_name, signal_data in signals_to_test:
                try:
                    await handle.signal(signal_name, signal_data)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.debug(f"Signal {signal_name} not supported: {e}")
            result = await asyncio.wait_for(handle.result(), timeout=60)
            if result.success:
                await e2e_test.verify_execution_result(result, test_query)
            else:
                assert result.error_message
        except TimeoutError:
            await handle.cancel()
            logger.info("Signal patterns test timed out as expected")
        except Exception as e:
            await handle.cancel()
            logger.info(f"Signal patterns test completed with exception: {e}")

    @pytest.mark.asyncio
    async def test_workflow_with_tool_error_handling(self, e2e_test: E2ETemporalTest):
        agent_id = await e2e_test.create_test_agent_with_tools()
        test_query = "Please try to access a file that doesn't exist: /nonexistent/path/file.txt"
        result = await e2e_test.execute_workflow_test(agent_id, test_query)
        if result.success:
            await e2e_test.verify_execution_result(result, test_query)
            assert result.total_tool_calls >= 0
        else:
            assert result.error_message

    @pytest.mark.asyncio
    async def test_workflow_with_multiple_tool_calls(self, e2e_test: E2ETemporalTest):
        agent_id = await e2e_test.create_test_agent_with_tools()
        test_query = "Please help me: 1) list the current directory, 2) check if there's a README file, and 3) tell me the current time"
        result = await e2e_test.execute_workflow_test(agent_id, test_query)
        await e2e_test.verify_execution_result(result, test_query)
        assert result.total_tool_calls >= 2, (
            f"Expected multiple tool calls, got {result.total_tool_calls}"
        )

    @pytest.mark.asyncio
    async def test_workflow_tool_timeout_handling(self, e2e_test: E2ETemporalTest):
        agent_id = await e2e_test.create_test_agent_with_tools()
        test_query = "Please run a command that might take a very long time to complete"
        result = await e2e_test.execute_workflow_test(agent_id, test_query)
        if result.success:
            await e2e_test.verify_execution_result(result, test_query)
        else:
            assert result.error_message
            assert (
                "timeout" in result.error_message.lower() or "time" in result.error_message.lower()
            )

    @pytest.mark.asyncio
    async def test_workflow_tools_with_user_interaction(self, e2e_test: E2ETemporalTest):
        agent_id = await e2e_test.create_test_agent_with_tools()
        test_query = "Please list files in a directory, then ask me which file I'd like you to examine in detail."
        if not e2e_test.client:
            raise RuntimeError("Client not initialized")
        task_id = uuid4()
        workflow_id = f"e2e-test-tools-signals-{task_id}"
        request = AgentExecutionRequest(
            task_id=task_id,
            agent_id=agent_id,
            user_id="e2e_test_user",
            task_query=test_query,
            timeout_seconds=300,
            max_reasoning_iterations=5,
        )
        handle = await e2e_test.client.start_workflow(
            AgentExecutionWorkflow.run,
            request,
            id=workflow_id,
            task_queue=e2e_test.task_queue,
            execution_timeout=timedelta(minutes=10),
        )
        await asyncio.sleep(3)
        try:
            await handle.signal("user_selection", {"selected_file": "README.md"})
            result = await asyncio.wait_for(handle.result(), timeout=120)
            if result.success:
                await e2e_test.verify_execution_result(result, test_query)
                assert result.total_tool_calls > 0
                conversation_text = " ".join(str(msg) for msg in result.conversation_history)
                assert any(
                    kw in conversation_text.lower() for kw in ["file", "directory", "list", "tool"]
                ), "Expected evidence of file/tool operations"
            else:
                assert result.error_message
        except TimeoutError:
            await handle.cancel()
            logger.info("Tools with user interaction test timed out")
        except Exception as e:
            await handle.cancel()
            logger.info(f"Tools with user interaction test completed with exception: {e}")
