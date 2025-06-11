"""
Простые интеграционные тесты для AgentArea с Ollama
===================================================

Простые тесты, которые проверяют реальную работу с Ollama LLM.
Основаны на проверенном коде из simple_interactive_test.py

Запуск:
    cd core
    python tests/test_integration_simple.py
    
Или через pytest:
    cd core && pytest tests/test_integration_simple.py -v -s
"""

import asyncio
import pytest
from uuid import UUID, uuid4
from typing import List

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
OLLAMA_MODEL_INSTANCE_ID = "705e7c48-fcee-4266-8ce8-7502de7c68c8"


class SimpleEventBroker(EventBroker):
    """Simple event broker for testing."""
    async def publish(self, event) -> None:
        pass


class SimpleSecretManager(BaseSecretManager):
    """Simple secret manager for testing."""
    def __init__(self):
        self._secrets = {}
        
    async def get_secret(self, secret_name: str) -> str | None:
        return self._secrets.get(secret_name)
        
    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        self._secrets[secret_name] = secret_value
        
    async def delete_secret(self, secret_name: str) -> bool:
        return self._secrets.pop(secret_name, None) is not None


async def create_test_environment():
    """Creates a test environment with all necessary services."""
    
    # Initialize test services
    event_broker = SimpleEventBroker()
    secret_manager = SimpleSecretManager()
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
        
        return {
            "agent_repository": agent_repository,
            "agent_runner_service": agent_runner_service,
            "llm_model_instance_service": llm_model_instance_service,
        }


async def create_test_agent(agent_repository):
    """Creates a test agent for integration tests."""
    
    test_agent = Agent(
        id=str(uuid4()),
        name="integration_test_agent",
        description="Integration test agent for Ollama",
        instruction="""You are a helpful test AI assistant. Be concise and accurate.
        
When answering:
- Keep responses brief but informative
- Show that you understand the question
- Respond in the same language as the question""",
        model_id=OLLAMA_MODEL_INSTANCE_ID,
        status="active",
        planning=False,
        tools_config={},
        events_config={}
    )
    
    return await agent_repository.create(test_agent)


async def run_agent_query(agent_runner_service, agent_id: UUID, query: str) -> str:
    """Helper to run agent query and collect response."""
    
    response_parts: List[str] = []
    
    async for chunk in agent_runner_service.run_agent(
        agent_id=agent_id,
        user_id="test_user",
        query=query
    ):
        if chunk.get("type") == "content":
            content = chunk.get("content", "")
            if isinstance(content, str):
                response_parts.append(content)
        elif chunk.get("type") == "error":
            raise Exception(f"Agent error: {chunk.get('message', 'Unknown error')}")
    
    return "".join(response_parts)


# Test functions
async def test_simple_math():
    """Test simple math query to Ollama."""
    print("🧮 Testing simple math query...")
    
    services = await create_test_environment()
    agent = await create_test_agent(services["agent_repository"])
    
    try:
        query = "What is 7 + 5?"
        response = await run_agent_query(
            services["agent_runner_service"], 
            UUID(agent.id), 
            query
        )
        
        print(f"Query: {query}")
        print(f"Response: {response}")
        
        assert response is not None
        assert len(response) > 0
        assert "12" in response
        print("✅ Math test passed!")
        
    finally:
        # Cleanup
        await services["agent_repository"].delete(UUID(agent.id))


async def test_russian_language():
    """Test Russian language query."""
    print("🇷🇺 Testing Russian language query...")
    
    services = await create_test_environment()
    agent = await create_test_agent(services["agent_repository"])
    
    try:
        query = "Привет! Как тебя зовут?"
        response = await run_agent_query(
            services["agent_runner_service"], 
            UUID(agent.id), 
            query
        )
        
        print(f"Query: {query}")
        print(f"Response: {response}")
        
        assert response is not None
        assert len(response) > 0
        # Should respond to greeting
        greeting_words = ["привет", "здравствуй", "hello", "hi", "меня", "зовут", "я"]
        assert any(word in response.lower() for word in greeting_words)
        print("✅ Russian test passed!")
        
    finally:
        # Cleanup
        await services["agent_repository"].delete(UUID(agent.id))


async def test_creative_writing():
    """Test creative writing task."""
    print("🎨 Testing creative writing...")
    
    services = await create_test_environment()
    agent = await create_test_agent(services["agent_repository"])
    
    try:
        query = "Write one line about AI and programming"
        response = await run_agent_query(
            services["agent_runner_service"], 
            UUID(agent.id), 
            query
        )
        
        print(f"Query: {query}")
        print(f"Response: {response}")
        
        assert response is not None
        assert len(response) > 0
        # Should contain AI/programming related words
        tech_words = ["ai", "artificial", "intelligence", "program", "code", "algorithm", "computer"]
        assert any(word in response.lower() for word in tech_words)
        print("✅ Creative writing test passed!")
        
    finally:
        # Cleanup
        await services["agent_repository"].delete(UUID(agent.id))


async def test_model_instance_exists():
    """Test that the Ollama model instance exists in database."""
    print("🔍 Testing model instance exists...")
    
    services = await create_test_environment()
    
    model_instance = await services["llm_model_instance_service"].get(UUID(OLLAMA_MODEL_INSTANCE_ID))
    
    assert model_instance is not None
    assert model_instance.name == "Local Qwen2.5"
    print(f"✅ Found model instance: {model_instance.name}")


async def test_multiple_queries():
    """Test multiple queries to the same agent."""
    print("🔄 Testing multiple queries...")
    
    services = await create_test_environment()
    agent = await create_test_agent(services["agent_repository"])
    
    try:
        queries_and_checks = [
            ("What is 3 * 4?", "12"),
            ("What color is the sky?", "blue"),
            ("Name one fruit", ["apple", "banana", "orange", "grape"])
        ]
        
        for query, expected in queries_and_checks:
            response = await run_agent_query(
                services["agent_runner_service"], 
                UUID(agent.id), 
                query
            )
            
            print(f"Query: {query}")
            print(f"Response: {response}")
            
            assert response is not None
            assert len(response) > 0
            
            if isinstance(expected, str):
                assert expected in response.lower()
            elif isinstance(expected, list):
                assert any(exp in response.lower() for exp in expected)
            
            print(f"✅ Query '{query}' passed!")
        
        print("✅ Multiple queries test passed!")
        
    finally:
        # Cleanup
        await services["agent_repository"].delete(UUID(agent.id))


# Main execution
async def run_all_tests():
    """Run all integration tests."""
    print("🚀 Starting Ollama Integration Tests")
    print("=" * 50)
    
    tests = [
        test_model_instance_exists,
        test_simple_math,
        test_russian_language,
        test_creative_writing,
        test_multiple_queries,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            await test_func()
            passed += 1
            print(f"✅ {test_func.__name__} passed")
        except Exception as e:
            failed += 1
            print(f"❌ {test_func.__name__} failed: {e}")
        print("-" * 30)
    
    print(f"\n📊 Test Results:")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total: {passed + failed}")
    
    if failed == 0:
        print("🎉 All tests passed!")
    else:
        print(f"⚠️  {failed} tests failed")
    
    return failed == 0


# For pytest
@pytest.mark.asyncio
async def test_ollama_integration():
    """Main pytest entry point for all integration tests."""
    success = await run_all_tests()
    assert success, "Some integration tests failed"


if __name__ == "__main__":
    print("Running Ollama integration tests...")
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1) 