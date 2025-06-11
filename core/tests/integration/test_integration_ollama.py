"""
Интеграционные тесты для AgentArea с реальной Ollama LLM
=======================================================

Эти тесты выполняют реальные вызовы к Ollama модели через наш код.
Требуют запущенную БД, настроенные данные и работающую Ollama.

Запуск:
    pytest core/tests/test_integration_ollama.py -v
    
Или для отдельного теста:
    pytest core/tests/test_integration_ollama.py::test_simple_query -v -s
"""

import pytest
import asyncio
from uuid import UUID, uuid4
from typing import List, Dict, Any

from agentarea.config import get_database
from agentarea.modules.agents.domain.models import Agent
from agentarea.modules.agents.application.agent_builder_service import AgentBuilderService
from agentarea.modules.agents.application.agent_runner_service import AgentRunnerService
from agentarea.modules.agents.infrastructure.repository import AgentRepository
from agentarea.modules.llm.application.service import LLMModelInstanceService
from agentarea.modules.llm.infrastructure.llm_model_instance_repository import LLMModelInstanceRepository
from agentarea.modules.mcp.application.service import MCPServerInstanceService
from agentarea.modules.mcp.infrastructure.repository import MCPServerInstanceRepository, MCPServerRepository
from agentarea.common.events.broker import EventBroker
from agentarea.common.infrastructure.secret_manager import BaseSecretManager
from google.adk.sessions import InMemorySessionService


# Test configuration
OLLAMA_MODEL_INSTANCE_ID = "705e7c48-fcee-4266-8ce8-7502de7c68c8"  # From our setup
TEST_AGENT_NAME = "integration_test_agent"
TEST_USER_ID = "integration_test_user"


class TestEventBroker(EventBroker):
    """Simple event broker for testing."""
    
    async def publish(self, event: Any) -> None:
        pass  # No-op for tests


class TestSecretManager(BaseSecretManager):
    """Simple secret manager for testing."""
    
    def __init__(self):
        self._secrets: Dict[str, str] = {}
        
    async def get_secret(self, secret_name: str) -> str | None:
        return self._secrets.get(secret_name)
        
    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        self._secrets[secret_name] = secret_value
        
    async def delete_secret(self, secret_name: str) -> bool:
        return self._secrets.pop(secret_name, None) is not None


@pytest.fixture
async def test_services():
    """Создает тестовые сервисы для интеграционных тестов."""
    
    # Initialize test services
    event_broker = TestEventBroker()
    secret_manager = TestSecretManager()
    session_service = InMemorySessionService()
    
    db = get_database()
    
    async with db.get_db() as session:
        # Initialize repositories
        agent_repository = AgentRepository(session)
        llm_model_instance_repository = LLMModelInstanceRepository(session)
        mcp_server_instance_repository = MCPServerInstanceRepository(session)
        mcp_server_repository = MCPServerRepository(session)
        
        # Initialize services
        llm_model_instance_service = LLMModelInstanceService(
            repository=llm_model_instance_repository,
            event_broker=event_broker,
            secret_manager=secret_manager
        )
        
        mcp_server_instance_service = MCPServerInstanceService(
            repository=mcp_server_instance_repository,
            event_broker=event_broker,
            mcp_server_repository=mcp_server_repository
        )
        
        agent_builder_service = AgentBuilderService(
            repository=agent_repository,
            event_broker=event_broker,
            llm_model_instance_service=llm_model_instance_service,
            mcp_server_instance_service=mcp_server_instance_service
        )
        
        agent_runner_service = AgentRunnerService(
            repository=agent_repository,
            event_broker=event_broker,
            llm_model_instance_service=llm_model_instance_service,
            session_service=session_service,
            agent_builder_service=agent_builder_service
        )
        
        yield {
            "agent_repository": agent_repository,
            "agent_builder_service": agent_builder_service,
            "agent_runner_service": agent_runner_service,
            "llm_model_instance_service": llm_model_instance_service,
        }


@pytest.fixture
async def test_agent(test_services):
    """Создает тестового агента для интеграционных тестов."""
    
    services = await test_services.__anext__()
    agent_repository = services["agent_repository"]
    
    # Try to find existing test agent first
    existing_agents = await agent_repository.list()
    for agent in existing_agents:
        if agent.name == TEST_AGENT_NAME:
            yield agent
            return
    
    # Create new test agent if not found
    test_agent = Agent(
        id=str(uuid4()),
        name=TEST_AGENT_NAME,
        description="Integration test agent for Ollama",
        instruction="""You are a test AI assistant. Be helpful, concise, and accurate.
        
When answering:
- Keep responses brief but informative
- Show that you understand the question
- Respond in the same language as the question
- Be friendly and professional""",
        model_id=OLLAMA_MODEL_INSTANCE_ID,
        status="active",
        planning=False,
        tools_config={},
        events_config={}
    )
    
    created_agent = await agent_repository.create(test_agent)
    yield created_agent
    
    # Cleanup: delete the agent after test
    try:
        await agent_repository.delete(UUID(created_agent.id))
    except Exception:
        pass  # Best effort cleanup


async def run_agent_and_collect_response(agent_runner_service, agent_id: UUID, query: str) -> str:
    """Helper function to run agent and collect full response."""
    response_parts: List[str] = []
    
    async for chunk in agent_runner_service.run_agent(
        agent_id=agent_id,
        user_id=TEST_USER_ID,
        query=query
    ):
        if chunk.get("type") == "content":
            content = chunk.get("content", "")
            if isinstance(content, str):
                response_parts.append(content)
        elif chunk.get("type") == "error":
            raise Exception(f"Agent error: {chunk.get('message', 'Unknown error')}")
    
    return "".join(response_parts)


@pytest.mark.asyncio
async def test_simple_query(test_services, test_agent):
    """Тест простого запроса к Ollama модели."""
    
    services = await test_services.__anext__()
    agent_runner_service = services["agent_runner_service"]
    
    # Test simple math question
    query = "What is 2 + 2?"
    response = await run_agent_and_collect_response(
        agent_runner_service, 
        UUID(test_agent.id), 
        query
    )
    
    print(f"Query: {query}")
    print(f"Response: {response}")
    
    # Assertions
    assert response is not None
    assert len(response) > 0
    assert "4" in response  # Should contain the answer


@pytest.mark.asyncio
async def test_russian_query(test_services, test_agent):
    """Тест запроса на русском языке."""
    
    services = await test_services.__anext__()
    agent_runner_service = services["agent_runner_service"]
    
    # Test Russian question
    query = "Привет! Как дела?"
    response = await run_agent_and_collect_response(
        agent_runner_service, 
        UUID(test_agent.id), 
        query
    )
    
    print(f"Query: {query}")
    print(f"Response: {response}")
    
    # Assertions
    assert response is not None
    assert len(response) > 0
    # Should respond in Russian or at least acknowledge the greeting
    assert any(word in response.lower() for word in ["привет", "здравствуй", "дела", "хорошо", "отлично", "hello", "hi"])


@pytest.mark.asyncio
async def test_creative_task(test_services, test_agent):
    """Тест творческой задачи."""
    
    services = await test_services.__anext__()
    agent_runner_service = services["agent_runner_service"]
    
    # Test creative writing
    query = "Write a very short poem about programming in 2 lines"
    response = await run_agent_and_collect_response(
        agent_runner_service, 
        UUID(test_agent.id), 
        query
    )
    
    print(f"Query: {query}")
    print(f"Response: {response}")
    
    # Assertions
    assert response is not None
    assert len(response) > 0
    # Should be creative and contain some programming-related words
    programming_words = ["code", "program", "debug", "compile", "algorithm", "function", "variable"]
    assert any(word in response.lower() for word in programming_words)


@pytest.mark.asyncio
async def test_explanation_task(test_services, test_agent):
    """Тест задачи объяснения концепции."""
    
    services = await test_services.__anext__()
    agent_runner_service = services["agent_runner_service"]
    
    # Test explanation
    query = "Explain what is machine learning in one sentence"
    response = await run_agent_and_collect_response(
        agent_runner_service, 
        UUID(test_agent.id), 
        query
    )
    
    print(f"Query: {query}")
    print(f"Response: {response}")
    
    # Assertions
    assert response is not None
    assert len(response) > 0
    # Should contain ML-related terms
    ml_words = ["machine learning", "algorithm", "data", "model", "artificial", "intelligence", "learn"]
    assert any(word in response.lower() for word in ml_words)


@pytest.mark.asyncio
async def test_multiple_queries_same_agent(test_services, test_agent):
    """Тест нескольких последовательных запросов к одному агенту."""
    
    services = await test_services.__anext__()
    agent_runner_service = services["agent_runner_service"]
    
    queries = [
        "What is 5 x 3?",
        "What is the capital of France?", 
        "Name one programming language"
    ]
    
    responses = []
    
    for query in queries:
        response = await run_agent_and_collect_response(
            agent_runner_service, 
            UUID(test_agent.id), 
            query
        )
        responses.append(response)
        print(f"Query: {query}")
        print(f"Response: {response}")
        print("-" * 50)
    
    # Assertions
    assert len(responses) == 3
    assert all(len(r) > 0 for r in responses)
    
    # Check specific answers
    assert "15" in responses[0]  # 5 x 3 = 15
    assert "paris" in responses[1].lower()  # Capital of France
    # Third response should contain a programming language
    prog_langs = ["python", "javascript", "java", "c++", "c#", "go", "rust", "ruby"]
    assert any(lang in responses[2].lower() for lang in prog_langs)


@pytest.mark.asyncio
async def test_llm_model_instance_exists(test_services):
    """Тест существования настроенного LLM model instance."""
    
    services = await test_services.__anext__()
    llm_service = services["llm_model_instance_service"]
    
    # Check that our configured model instance exists
    model_instance = await llm_service.get(UUID(OLLAMA_MODEL_INSTANCE_ID))
    
    assert model_instance is not None
    assert model_instance.name == "Local Qwen2.5"
    assert model_instance.model_id == "796d7648-804f-4d0e-9657-9d122957ee27"
    print(f"Found model instance: {model_instance.name}")


@pytest.mark.asyncio 
async def test_agent_config_building(test_services, test_agent):
    """Тест построения конфигурации агента."""
    
    services = await test_services.__anext__()
    agent_builder_service = services["agent_builder_service"]
    
    # Build agent config
    config = await agent_builder_service.build_agent_config(UUID(test_agent.id))
    
    assert config is not None
    assert config["name"] == TEST_AGENT_NAME
    assert config["model_instance"] is not None
    assert config["tools_config"] is not None
    assert "planning_enabled" in config
    
    print(f"Built config for agent: {config['name']}")
    print(f"Model instance: {config['model_instance'].name}")


# Если запускается как скрипт, выполнить все тесты
if __name__ == "__main__":
    import sys
    
    async def run_all_tests():
        """Запуск всех тестов вручную для отладки."""
        print("🧪 Запуск интеграционных тестов Ollama...")
        
        try:
            # Setup
            test_broker = TestEventBroker()
            test_secret = TestSecretManager()
            test_session = InMemorySessionService()
            
            db = get_database()
            
            async with db.get_db() as session:
                # Initialize services
                agent_repository = AgentRepository(session)
                llm_repo = LLMModelInstanceRepository(session)
                mcp_repo = MCPServerInstanceRepository(session)
                mcp_server_repo = MCPServerRepository(session)
                
                llm_service = LLMModelInstanceService(llm_repo, test_broker, test_secret)
                mcp_service = MCPServerInstanceService(mcp_repo, test_broker, mcp_server_repo)
                
                agent_builder = AgentBuilderService(
                    agent_repository, test_broker, llm_service, mcp_service
                )
                
                agent_runner = AgentRunnerService(
                    agent_repository, test_broker, llm_service, test_session, agent_builder
                )
                
                # Create test agent
                test_agent = Agent(
                    id=str(uuid4()),
                    name="manual_test_agent",
                    description="Manual test agent",
                    instruction="You are a helpful assistant. Be brief and accurate.",
                    model_id=OLLAMA_MODEL_INSTANCE_ID,
                    status="active",
                    planning=False,
                    tools_config={},
                    events_config={}
                )
                
                created_agent = await agent_repository.create(test_agent)
                
                # Run a simple test
                print("🤖 Testing simple query...")
                response = await run_agent_and_collect_response(
                    agent_runner, UUID(created_agent.id), "Hello! What is 2+2?"
                )
                
                print(f"✅ Response: {response}")
                
                # Cleanup
                await agent_repository.delete(UUID(created_agent.id))
                
        except Exception as e:
            print(f"❌ Test failed: {e}")
            sys.exit(1)
        
        print("🎉 All tests completed!")
    
    asyncio.run(run_all_tests()) 