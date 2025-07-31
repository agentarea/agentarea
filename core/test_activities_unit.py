#!/usr/bin/env python3
"""
Unit tests for agent execution activities to verify all dependencies inject correctly.
"""
import asyncio
import sys
from uuid import UUID, uuid4
from unittest.mock import Mock, AsyncMock

# Add the core directory to the path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

from agentarea_common.config import get_database
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_execution.interfaces import ActivityDependencies
from agentarea_execution.activities.agent_execution_activities import make_agent_activities


async def test_build_agent_config_activity():
    """Test build_agent_config_activity with proper dependency injection."""
    print("🧪 Testing build_agent_config_activity...")
    
    try:
        # Step 1: Create mock dependencies
        print("1. Creating mock dependencies...")
        mock_settings = Mock()
        mock_event_broker = Mock()
        mock_secret_manager = Mock()
        
        dependencies = ActivityDependencies(
            settings=mock_settings,
            event_broker=mock_event_broker,
            secret_manager=mock_secret_manager
        )
        
        # Step 2: Create activities
        print("2. Creating activities...")
        activities = make_agent_activities(dependencies)
        
        # Find the build_agent_config_activity
        build_agent_config_activity = None
        for activity in activities:
            if hasattr(activity, '__name__') and 'build_agent_config' in activity.__name__:
                build_agent_config_activity = activity
                break
        
        if not build_agent_config_activity:
            print("❌ build_agent_config_activity not found in activities list")
            return False
        
        print("✅ build_agent_config_activity found")
        
        # Step 3: Test activity execution with real database
        print("3. Testing activity execution...")
        
        # Use real database and user context
        database = get_database()
        user_context_data = {
            "user_id": "dev-user",
            "workspace_id": "system"
        }
        
        agent_id = UUID("e4f95a11-c405-49ca-97d3-3e25d60dbd2c")  # Use existing agent
        
        # Execute the activity
        result = await build_agent_config_activity(
            agent_id=agent_id,
            user_context_data=user_context_data
        )
        
        print(f"✅ Activity executed successfully!")
        print(f"   - Agent ID: {result.get('id')}")
        print(f"   - Agent Name: {result.get('name')}")
        print(f"   - Model ID: {result.get('model_id')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_discover_available_tools_activity():
    """Test discover_available_tools_activity with proper dependency injection."""
    print("\n🧪 Testing discover_available_tools_activity...")
    
    try:
        # Step 1: Create mock dependencies
        print("1. Creating mock dependencies...")
        mock_settings = Mock()
        mock_event_broker = Mock()
        mock_secret_manager = Mock()
        
        dependencies = ActivityDependencies(
            settings=mock_settings,
            event_broker=mock_event_broker,
            secret_manager=mock_secret_manager
        )
        
        # Step 2: Create activities
        print("2. Creating activities...")
        activities = make_agent_activities(dependencies)
        
        # Find the discover_available_tools_activity
        discover_tools_activity = None
        for activity in activities:
            if hasattr(activity, '__name__') and 'discover_available_tools' in activity.__name__:
                discover_tools_activity = activity
                break
        
        if not discover_tools_activity:
            print("❌ discover_available_tools_activity not found in activities list")
            return False
        
        print("✅ discover_available_tools_activity found")
        
        # Step 3: Test activity execution
        print("3. Testing activity execution...")
        
        user_context_data = {
            "user_id": "dev-user",
            "workspace_id": "system"
        }
        
        agent_id = UUID("e4f95a11-c405-49ca-97d3-3e25d60dbd2c")  # Use existing agent
        
        # Execute the activity
        result = await discover_tools_activity(
            agent_id=agent_id,
            user_context_data=user_context_data
        )
        
        print(f"✅ Activity executed successfully!")
        print(f"   - Found {len(result)} tools")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_service_instantiation():
    """Test that all services can be instantiated with correct parameters."""
    print("\n🧪 Testing service instantiation...")
    
    try:
        # Test database and user context
        database = get_database()
        user_context = UserContext(
            user_id="dev-user",
            workspace_id="system"
        )
        
        async with database.async_session_factory() as session:
            # Test RepositoryFactory
            print("1. Testing RepositoryFactory...")
            repository_factory = RepositoryFactory(session, user_context)
            print("✅ RepositoryFactory created")
            
            # Test AgentService
            print("2. Testing AgentService...")
            from agentarea_agents.application.agent_service import AgentService
            from agentarea_common.events.router import get_event_router
            from agentarea_common.config import get_settings
            
            settings = get_settings()
            event_broker = get_event_router(settings.broker)
            
            agent_service = AgentService(
                repository_factory=repository_factory,
                event_broker=event_broker
            )
            print("✅ AgentService created")
            
            # Test MCPServerInstanceService
            print("3. Testing MCPServerInstanceService...")
            from agentarea_mcp.application.service import MCPServerInstanceService
            from agentarea_secrets import get_real_secret_manager
            
            secret_manager = get_real_secret_manager()
            
            mcp_service = MCPServerInstanceService(
                repository_factory=repository_factory,
                event_broker=event_broker,
                secret_manager=secret_manager
            )
            print("✅ MCPServerInstanceService created")
            
            # Test agent retrieval
            print("4. Testing agent retrieval...")
            agent_id = UUID("e4f95a11-c405-49ca-97d3-3e25d60dbd2c")
            agent = await agent_service.get(agent_id)
            
            if agent:
                print(f"✅ Agent retrieved: {agent.name}")
            else:
                print("❌ Agent not found")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ Service instantiation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all unit tests."""
    print("🚀 Running unit tests for agent execution activities...\n")
    
    tests = [
        test_service_instantiation,
        test_build_agent_config_activity,
        test_discover_available_tools_activity,
    ]
    
    results = []
    for test in tests:
        result = await test()
        results.append(result)
    
    print(f"\n📊 Test Results:")
    print(f"   - Passed: {sum(results)}/{len(results)}")
    print(f"   - Failed: {len(results) - sum(results)}/{len(results)}")
    
    if all(results):
        print("🎉 All tests passed! Activities are ready for production.")
    else:
        print("❌ Some tests failed. Fix issues before deploying.")
    
    return all(results)


if __name__ == "__main__":
    asyncio.run(run_all_tests())