import asyncio
import logging
import os
import threading
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from temporalio.client import Client
from temporalio.worker import Worker

from agentarea_agents.infrastructure.di_container import initialize_di_container
from agentarea_common.config import Database, get_settings
from agentarea_execution import ActivityDependencies, create_activities_for_worker
from agentarea_execution.models import AgentExecutionRequest, AgentExecutionResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("TEMPORAL_SERVER_URL", "localhost:7233")
os.environ.setdefault("TEMPORAL_NAMESPACE", "default")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEBUG", "true")
os.environ.update({"REDIS_URL": "redis://localhost:6379"})


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
            namespace=self.settings.workflow.TEMPORAL_NAMESPACE
        )

    async def _create_test_llm_infrastructure(self):
        from agentarea_common.events.broker import EventBroker
        from agentarea_common.infrastructure.secret_manager import BaseSecretManager
        from agentarea_llm.application.llm_model_service import LLMModelService
        from agentarea_llm.application.service import LLMModelInstanceService
        from agentarea_llm.infrastructure.llm_model_instance_repository import LLMModelInstanceRepository
        from agentarea_llm.infrastructure.llm_model_repository import LLMModelRepository

        class TestEventBroker(EventBroker):
            async def publish(self, event):
                pass

        class TestSecretManager(BaseSecretManager):
            async def get_secret(self, secret_name: str):
                return "test-api-key"
            async def set_secret(self, secret_name: str, secret_value: str):
                pass
            async def delete_secret(self, secret_name: str):
                pass

        db = Database(self.settings.database)
        async with db.get_db() as session:
            llm_model_repository = LLMModelRepository(session)
            llm_model_service = LLMModelService(llm_model_repository, TestEventBroker())
            llm_instance_repository = LLMModelInstanceRepository(session)
            llm_instance_service = LLMModelInstanceService(llm_instance_repository, TestEventBroker(), TestSecretManager())
            try:
                model = await llm_model_service.create_llm_model(
                    name="qwen2.5",
                    description="Qwen 2.5 model via Ollama for E2E testing",
                    provider="183a5efc-2525-4a1e-aded-1a5d5e9ff13b",
                    model_name="qwen2.5",
                    endpoint_url=None,
                    context_window="4096",
                    is_public=True
                )
                self.test_model_id = str(model.id)
            except Exception:
                models = await llm_model_repository.list(provider="183a5efc-2525-4a1e-aded-1a5d5e9ff13b")
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
                    is_public=True
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
        """Setup the basic dependencies needed by activities to create their own services."""
        from agentarea_common.events.router import get_event_router
        from agentarea_common.infrastructure.infisical_factory import get_real_secret_manager
        
        # Get event broker
        event_broker = get_event_router(self.settings.broker)
        
        # Get secret manager (reads configuration from environment)
        secret_manager = get_real_secret_manager()
        
        # Create activity dependencies container
        self.activity_dependencies = ActivityDependencies(
            settings=self.settings,
            event_broker=event_broker,
            secret_manager=secret_manager
        )

    async def _check_temporal_server(self):
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex(("localhost", 7233))
        sock.close()
        if result != 0:
            raise ConnectionError("Temporal server not available at localhost:7233")

    async def _check_database(self):
        from sqlalchemy import text
        from agentarea_agents.infrastructure.repository import AgentRepository
        db = Database(self.settings.database)
        async with db.get_db() as session:
            await session.execute(text("SELECT 1"))
            agent_repository = AgentRepository(session)
            agents = await agent_repository.list()
            if not agents:
                logger.warning("No agents found in database")

    async def _check_redis(self):
        import redis.asyncio as redis
        redis_url = getattr(self.settings.broker, 'REDIS_URL', 'redis://localhost:6379')
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
                shutdown_monitor = threading.Thread(target=monitor_shutdown, daemon=True)
                shutdown_monitor.start()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    if self.worker:
                        await self.worker.shutdown()
                finally:
                    shutdown_monitor.join(timeout=1.0)
            try:
                loop.run_until_complete(run_with_shutdown())
            finally:
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                finally:
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

        class TestEventBroker(EventBroker):
            async def publish(self, event):
                pass

        db = Database(self.settings.database)
        async with db.get_db() as session:
            agent_repository = AgentRepository(session)
            agent_service = AgentService(agent_repository, TestEventBroker())
            existing_agents = await agent_repository.list()
            test_agents = [a for a in existing_agents if "test" in a.name.lower() or "Test" in a.name]
            if test_agents:
                agent = test_agents[0]
                agent.model_id = str(self.test_model_instance_id)
                updated_agent = await agent_service.update(agent)
                self.test_agent_id = updated_agent.id
                return updated_agent.id
            elif existing_agents:
                agent = existing_agents[0]
                agent.model_id = str(self.test_model_instance_id)
                updated_agent = await agent_service.update(agent)
                self.test_agent_id = updated_agent.id
                return updated_agent.id
            else:
                new_agent = Agent(
                    name="E2E Test Agent",
                    description="Agent created for E2E testing with qwen2.5",
                    instruction="You are a helpful assistant for testing purposes.",
                    status="active",
                    model_id=str(self.test_model_instance_id),
                    tools_config={"mcp_servers": []},
                    events_config={},
                    planning=False
                )
                created_agent = await agent_service.create(new_agent)
                self.test_agent_id = created_agent.id
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
            result = await asyncio.wait_for(handle.result(), timeout=300)
            return result
        except TimeoutError:
            await handle.cancel()
            raise
            
    async def verify_execution_result(self, result: AgentExecutionResult, expected_query: str):
        assert result.success, f"Workflow failed: {result.error_message}"
        assert result.final_response is not None and len(result.final_response.strip()) > 0
        assert len(result.conversation_history) >= 1
        assert result.task_id is not None
        assert result.agent_id is not None
        assert result.reasoning_iterations_used >= 0
        assert result.total_tool_calls >= 0

    async def cleanup(self):
        await self.stop_test_worker()
        if self.client:
            try:
                if hasattr(self.client, 'shutdown'):
                    await self.client.shutdown()
                elif hasattr(self.client, 'close'):
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
                if hasattr(test_framework, 'worker_shutdown_event'):
                    test_framework.worker_shutdown_event.set()
                if hasattr(test_framework, 'worker_thread') and test_framework.worker_thread:
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
        assert result.final_response is not None
        assert "42" in result.final_response or "forty" in result.final_response.lower()
            
    @pytest.mark.asyncio
    async def test_multiple_concurrent_executions(self, e2e_test: E2ETemporalTest, test_agent_id: UUID):
        test_queries = [
            "Count from 1 to 5",
            "What are the primary colors?", 
            "Name three planets in our solar system"
        ]
        tasks = [e2e_test.execute_workflow_test(test_agent_id, query) for query in test_queries]
        results = await asyncio.gather(*tasks)
        for i, result in enumerate(results):
            await e2e_test.verify_execution_result(result, test_queries[i])
        
    @pytest.mark.asyncio
    async def test_workflow_with_error_handling(self, e2e_test: E2ETemporalTest, test_agent_id: UUID):
        test_query = "Please explain quantum physics in exactly 10 words."
        result = await e2e_test.execute_workflow_test(test_agent_id, test_query)
        if result.success:
            await e2e_test.verify_execution_result(result, test_query)
        else:
            assert result.error_message is not None


