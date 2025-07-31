#!/usr/bin/env python3
"""
Debug script to test the build_agent_config_activity directly.
"""
import asyncio
import sys
from uuid import UUID

# Add the core directory to the path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

from agentarea_common.config import get_database
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_agents.application.agent_service import AgentService
from agentarea_common.events.router import get_event_router
from agentarea_common.config import get_settings


async def test_build_agent_config_activity():
    """Test the build_agent_config_activity logic directly."""
    print("🔍 Testing build_agent_config_activity logic...")
    
    try:
        # Step 1: Create user context
        print("\n1. Creating user context...")
        user_context_data = {
            "user_id": "dev-user",  # Use the actual user_id from database
            "workspace_id": "system"  # Use the actual workspace_id from database
        }
        
        user_context = UserContext(
            user_id=user_context_data["user_id"],
            workspace_id=user_context_data["workspace_id"]
        )
        print(f"✅ User context created: {user_context}")
        
        # Step 2: Create database session and services
        print("\n2. Creating database session and services...")
        database = get_database()
        async with database.async_session_factory() as session:
            # Create repository factory
            repository_factory = RepositoryFactory(session, user_context)
            
            # Create event broker
            settings = get_settings()
            event_broker = get_event_router(settings.broker)
            
            # Create agent service
            agent_service = AgentService(
                repository_factory=repository_factory, 
                event_broker=event_broker
            )
            print("✅ Services created successfully")
            
            # Step 3: Test agent retrieval
            print("\n3. Testing agent retrieval...")
            agent_id = UUID("31589c71-f085-4a98-8a62-878f11e8a699")
            agent = await agent_service.get(agent_id)
            
            if not agent:
                print(f"❌ Agent {agent_id} not found")
                return
            
            print(f"✅ Agent retrieved: {agent.name}")
            
            # Step 4: Build configuration
            print("\n4. Building agent configuration...")
            agent_config = {
                "id": str(agent.id),
                "name": agent.name,
                "description": agent.description,
                "instruction": agent.instruction,
                "model_id": agent.model_id,
                "tools_config": agent.tools_config or {},
                "events_config": agent.events_config or {},
                "planning": agent.planning,
            }
            
            print(f"✅ Agent configuration built successfully")
            print(f"   - Agent ID: {agent_config['id']}")
            print(f"   - Agent Name: {agent_config['name']}")
            print(f"   - Model ID: {agent_config['model_id']}")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n🎉 build_agent_config_activity logic test completed successfully!")


if __name__ == "__main__":
    asyncio.run(test_build_agent_config_activity())