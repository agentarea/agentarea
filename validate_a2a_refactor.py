#!/usr/bin/env python3
"""Validate A2A protocol refactoring by checking file structure."""

import os
import re

def validate_a2a_refactor():
    """Validate that A2A refactoring was completed correctly."""
    
    print("🔍 Validating A2A Protocol Refactoring")
    print("=" * 50)
    
    # 1. Check that agents_a2a.py exists
    agents_a2a_path = "core/apps/api/agentarea_api/api/v1/agents_a2a.py"
    if os.path.exists(agents_a2a_path):
        print("✅ A2A protocol file exists: agents_a2a.py")
    else:
        print("❌ Missing A2A protocol file: agents_a2a.py")
        return False
    
    # 2. Check that agents_a2a.py has the expected endpoints
    with open(agents_a2a_path, 'r') as f:
        content = f.read()
    
    expected_endpoints = [
        '@router.post("/rpc")',
        '@router.get("/card")',
        'handle_agent_jsonrpc',
        'get_agent_card',
        'handle_message_send',
        'handle_message_stream',
        'handle_task_get',
        'handle_task_cancel',
        'handle_agent_card'
    ]
    
    for endpoint in expected_endpoints:
        if endpoint in content:
            print(f"✅ Found expected endpoint/function: {endpoint}")
        else:
            print(f"❌ Missing endpoint/function: {endpoint}")
            return False
    
    # 3. Check that agents.py includes the A2A subrouter
    agents_path = "core/apps/api/agentarea_api/api/v1/agents.py"
    if os.path.exists(agents_path):
        with open(agents_path, 'r') as f:
            agents_content = f.read()
        
        if "from . import agents_a2a" in agents_content:
            print("✅ agents.py imports A2A subrouter")
        else:
            print("❌ agents.py missing A2A subrouter import")
            return False
        
        if "router.include_router(" in agents_content and "agents_a2a.router" in agents_content:
            print("✅ agents.py includes A2A subrouter")
        else:
            print("❌ agents.py missing A2A subrouter inclusion")
            return False
    
    # 4. Check that the URL structure is correct
    if 'prefix="/{agent_id}"' in agents_content:
        print("✅ A2A subrouter has correct prefix: /{agent_id}")
    else:
        print("❌ A2A subrouter missing correct prefix")
        return False
    
    # 5. Check that agent cards reference the correct URL
    if 'url=f"http://localhost:8000/v1/agents/{agent_id}/rpc"' in content:
        print("✅ Agent cards reference correct agent-specific RPC URL")
    else:
        print("❌ Agent cards missing correct RPC URL")
        return False
    
    return True

def show_new_url_structure():
    """Show the new A2A URL structure."""
    print("\n📋 New A2A URL Structure:")
    print("  /v1/agents/{agent_id}/rpc     - A2A JSON-RPC endpoint (NEW)")
    print("  /v1/agents/{agent_id}/card    - A2A agent discovery (NEW)")
    print("  /v1/agents/{agent_id}/tasks/  - REST task endpoints (existing)")
    print("  /v1/agents/                   - Agent CRUD endpoints (existing)")
    
    print("\n🔄 Changed from:")
    print("  /v1/protocol/rpc              - Global RPC endpoint (OLD)")
    print("  /v1/protocol/agents/{id}/card - Global agent discovery (OLD)")
    
    print("\n✅ Benefits of agent-specific endpoints:")
    print("  • Each agent has its own A2A communication endpoint")
    print("  • Better security isolation between agents")
    print("  • Agent-specific authentication and authorization")
    print("  • Scales better with large numbers of agents")
    print("  • Follows A2A protocol specification correctly")

if __name__ == "__main__":
    success = validate_a2a_refactor()
    
    if success:
        print("\n🎉 A2A Protocol Refactoring Validation PASSED!")
        show_new_url_structure()
        print("\n🚀 Ready to implement A2A protocol with proper agent-specific endpoints!")
    else:
        print("\n❌ A2A Protocol Refactoring Validation FAILED!")
        print("Please check the implementation and fix any issues.")