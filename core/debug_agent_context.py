#!/usr/bin/env python3
"""
Debug script to check agent user context in database.
"""
import asyncio
import sys
from uuid import UUID

# Add the core directory to the path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

from agentarea_common.config import get_database
from sqlalchemy import text


async def check_agent_context():
    """Check agent user context in database."""
    print("🔍 Checking agent user context in database...")
    
    database = get_database()
    async with database.async_session_factory() as session:
        # Query agents table directly
        result = await session.execute(
            text("SELECT id, name, created_by, workspace_id FROM agents WHERE id = :agent_id"),
            {"agent_id": "31589c71-f085-4a98-8a62-878f11e8a699"}
        )
        
        row = result.fetchone()
        if row:
            print(f"✅ Agent found in database:")
            print(f"   - ID: {row[0]}")
            print(f"   - Name: {row[1]}")
            print(f"   - Created by: {row[2]}")
            print(f"   - Workspace ID: {row[3]}")
        else:
            print("❌ Agent not found in database")
            
        # Also check all agents
        print("\n📋 All agents in database:")
        result = await session.execute(
            text("SELECT id, name, created_by, workspace_id FROM agents ORDER BY created_at DESC LIMIT 5")
        )
        
        for row in result.fetchall():
            print(f"   - {row[1]} (ID: {row[0]}, User: {row[2]}, Workspace: {row[3]})")


if __name__ == "__main__":
    asyncio.run(check_agent_context())