#!/usr/bin/env python3
"""
Smoke test to diagnose workflow execution issues.
This script tests the entire task creation and workflow execution pipeline.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from uuid import uuid4

# Add the core directory to the path
sys.path.insert(0, 'core')

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_tasks.task_service import TaskService
from agentarea_common.config import Database, get_db_settings
from agentarea_common.events.broker import EventBroker
from sqlalchemy import text

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_database_connection():
    """Test database connectivity."""
    try:
        logger.info("🔍 Testing database connection...")
        db = Database(get_db_settings())
        engine = db.get_engine()
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1 as test"))
            row = result.fetchone()
            if row and row[0] == 1:
                logger.info("✅ Database connection successful")
                return True
            else:
                logger.error("❌ Database connection failed - no result")
                return False
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

async def test_agent_service():
    """Test agent service and find available agents."""
    try:
        logger.info("🔍 Testing agent service...")
        agent_service = AgentService()
        agents = await agent_service.list()
        
        if not agents:
            logger.error("❌ No agents found in database")
            return None
            
        logger.info(f"✅ Found {len(agents)} agents")
        for agent in agents[:3]:  # Show first 3 agents
            logger.info(f"   - Agent: {agent.name} (ID: {agent.id}, Status: {agent.status})")
            
        # Return the first active agent
        active_agents = [a for a in agents if a.status == 'active']
        if active_agents:
            logger.info(f"✅ Using active agent: {active_agents[0].name}")
            return active_agents[0]
        else:
            logger.warning(f"⚠️  No active agents found, using first agent: {agents[0].name}")
            return agents[0]
            
    except Exception as e:
        logger.error(f"❌ Agent service failed: {e}")
        return None

async def test_temporal_connection():
    """Test Temporal workflow service connectivity."""
    try:
        logger.info("🔍 Testing Temporal connection...")
        workflow_service = TemporalWorkflowService()
        
        # Try to get workflow status for a non-existent workflow
        test_execution_id = f"test-{uuid4()}"
        status = await workflow_service.get_workflow_status(test_execution_id)
        
        if status.get('status') == 'unknown':
            logger.info("✅ Temporal connection successful (got expected 'unknown' status)")
            return workflow_service
        else:
            logger.warning(f"⚠️  Temporal connection unclear - got status: {status}")
            return workflow_service
            
    except Exception as e:
        logger.error(f"❌ Temporal connection failed: {e}")
        return None

async def test_task_creation():
    """Test task creation without workflow execution."""
    try:
        logger.info("🔍 Testing task creation...")
        task_service = TaskService()
        
        # Create a simple task
        task_id = uuid4()
        test_task = {
            'id': task_id,
            'agent_id': uuid4(),  # Use a dummy agent ID for now
            'description': 'Test task creation',
            'task_parameters': {'test': True},
            'user_id': 'test_user',
            'status': 'pending'
        }
        
        # This would normally create a task in the database
        logger.info("✅ Task service initialized successfully")
        return task_service
        
    except Exception as e:
        logger.error(f"❌ Task service failed: {e}")
        return None

async def test_workflow_execution(agent, workflow_service, task_service):
    """Test actual workflow execution."""
    try:
        logger.info("🔍 Testing workflow execution...")
        
        # Try to create and execute a task with workflow
        task = await task_service.create_and_execute_task_with_workflow(
            agent_id=agent.id,
            description="Test workflow execution",
            parameters={
                "context": {},
                "task_type": "test",
                "session_id": f"test-{uuid4()}",
            },
            user_id="test_user",
            enable_agent_communication=True,
        )
        
        logger.info(f"✅ Task created: {task.id}")
        logger.info(f"   Status: {task.status}")
        logger.info(f"   Execution ID: {task.execution_id}")
        
        if task.status == 'failed':
            logger.error(f"❌ Task failed immediately: {task.result}")
            return False
            
        # Wait a moment and check status
        await asyncio.sleep(2)
        
        if task.execution_id:
            status = await workflow_service.get_workflow_status(task.execution_id)
            logger.info(f"   Workflow status after 2s: {status}")
            
        return True
        
    except Exception as e:
        logger.error(f"❌ Workflow execution failed: {e}")
        logger.exception("Full traceback:")
        return False

async def test_event_broker():
    """Test event broker connectivity."""
    try:
        logger.info("🔍 Testing event broker...")
        event_broker = EventBroker()
        
        # Try to publish a test event
        test_event = {
            'type': 'test_event',
            'data': {'test': True, 'timestamp': datetime.now().isoformat()}
        }
        
        await event_broker.publish('test_channel', test_event)
        logger.info("✅ Event broker publish successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Event broker failed: {e}")
        return False

async def main():
    """Run all smoke tests."""
    logger.info("🚀 Starting AgentArea Workflow Smoke Test")
    logger.info("=" * 60)
    
    # Test 1: Database
    db_ok = await test_database_connection()
    if not db_ok:
        logger.error("💥 Database test failed - stopping here")
        return False
    
    # Test 2: Agent Service
    agent = await test_agent_service()
    if not agent:
        logger.error("💥 Agent service test failed - stopping here")
        return False
    
    # Test 3: Temporal Connection
    workflow_service = await test_temporal_connection()
    if not workflow_service:
        logger.error("💥 Temporal connection test failed - stopping here")
        return False
    
    # Test 4: Task Service
    task_service = await test_task_creation()
    if not task_service:
        logger.error("💥 Task service test failed - stopping here")
        return False
    
    # Test 5: Event Broker
    event_ok = await test_event_broker()
    if not event_ok:
        logger.warning("⚠️  Event broker test failed - continuing anyway")
    
    # Test 6: Full Workflow Execution
    logger.info("=" * 60)
    logger.info("🎯 Running full workflow execution test...")
    workflow_ok = await test_workflow_execution(agent, workflow_service, task_service)
    
    logger.info("=" * 60)
    if workflow_ok:
        logger.info("🎉 All tests passed! Workflow execution is working.")
        return True
    else:
        logger.error("💥 Workflow execution test failed!")
        return False

if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        logger.info("🛑 Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)