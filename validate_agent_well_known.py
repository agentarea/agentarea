#!/usr/bin/env python3
"""Validate agent-specific well-known endpoints implementation."""

import os
import re

def validate_agent_well_known():
    """Validate that agent-specific well-known endpoints are properly implemented."""
    
    print("🔍 Validating Agent-Specific Well-Known Endpoints")
    print("=" * 60)
    
    # 1. Check that agents_well_known.py exists
    well_known_path = "core/apps/api/agentarea_api/api/v1/agents_well_known.py"
    if os.path.exists(well_known_path):
        print("✅ Agent well-known file exists: agents_well_known.py")
    else:
        print("❌ Missing agent well-known file: agents_well_known.py")
        return False
    
    # 2. Check that agents_well_known.py has the expected endpoints
    with open(well_known_path, 'r') as f:
        content = f.read()
    
    expected_endpoints = [
        '@router.get("/.well-known/agent.json")',
        '@router.get("/.well-known/a2a-info.json")',
        '@router.get("/.well-known/")',
        'get_agent_well_known_card',
        'get_agent_a2a_info',
        'get_agent_well_known_index',
        'create_agent_card_for_agent'
    ]
    
    for endpoint in expected_endpoints:
        if endpoint in content:
            print(f"✅ Found expected endpoint/function: {endpoint}")
        else:
            print(f"❌ Missing endpoint/function: {endpoint}")
            return False
    
    # 3. Check that agents.py includes the well-known subrouter
    agents_path = "core/apps/api/agentarea_api/api/v1/agents.py"
    if os.path.exists(agents_path):
        with open(agents_path, 'r') as f:
            agents_content = f.read()
        
        if "from . import agents_a2a, agents_well_known" in agents_content:
            print("✅ agents.py imports agent well-known subrouter")
        else:
            print("❌ agents.py missing agent well-known subrouter import")
            return False
        
        if "agents_well_known.router" in agents_content:
            print("✅ agents.py includes agent well-known subrouter")
        else:
            print("❌ agents.py missing agent well-known subrouter inclusion")
            return False
    
    # 4. Check well-known endpoints have correct paths
    if '/.well-known/agent.json' in content and '/.well-known/a2a-info.json' in content:
        print("✅ Agent well-known endpoints have correct paths")
    else:
        print("❌ Agent well-known endpoints missing correct paths")
        return False
    
    # 5. Check that agent-specific URLs are generated correctly
    if 'f"{base_url}/v1/agents/{agent_id}/rpc"' in content:
        print("✅ Agent-specific RPC URLs generated correctly")
    else:
        print("❌ Agent-specific RPC URLs not generated correctly")
        return False
    
    return True

def show_agent_well_known_structure():
    """Show the new agent-specific well-known URL structure."""
    print("\n📋 Agent-Specific Well-Known URL Structure:")
    print("  Main domain agent:")
    print("    domain.com/.well-known/agent.json           # Primary agent")
    print()
    print("  Individual agent well-known endpoints:")
    print("    /v1/agents/123/.well-known/agent.json       # Agent 123 discovery")
    print("    /v1/agents/456/.well-known/agent.json       # Agent 456 discovery")
    print("    /v1/agents/789/.well-known/a2a-info.json    # Agent 789 A2A info")
    print()
    print("  Future subdomain proxy targets:")
    print("    agent-123.domain.com/.well-known/agent.json → /v1/agents/123/.well-known/agent.json")
    print("    agent-456.domain.com/.well-known/agent.json → /v1/agents/456/.well-known/agent.json")
    print("    agent-789.domain.com/rpc                    → /v1/agents/789/rpc")
    
    print("\n🔄 Complete A2A Discovery & Communication Flow:")
    print("  1. domain.com/.well-known/agent.json         # Discover main agent")
    print("  2. /v1/agents/{id}/.well-known/agent.json    # Discover specific agent")
    print("  3. /v1/agents/{id}/rpc                       # Communicate with agent")
    print("  4. agent-{id}.domain.com/.well-known/        # Future: Direct subdomain access")
    
    print("\n✅ Benefits of agent-specific well-known:")
    print("  • Each agent has its own discoverable endpoint")
    print("  • A2A compliant architecture")
    print("  • Ready for subdomain proxy setup")
    print("  • Maintains backward compatibility")
    print("  • Supports both single and multi-agent scenarios")

def show_proxy_examples():
    """Show examples of how subdomain proxy will work."""
    print("\n💡 Subdomain Proxy Examples:")
    print("  # Current working endpoints")
    print("  curl https://domain.com/.well-known/agent.json")
    print("  curl https://domain.com/v1/agents/123/.well-known/agent.json")
    print("  curl -X POST https://domain.com/v1/agents/123/rpc")
    print()
    print("  # Future subdomain endpoints (after proxy setup)")
    print("  curl https://agent-123.domain.com/.well-known/agent.json")
    print("  curl https://agent-456.domain.com/.well-known/agent.json")
    print("  curl -X POST https://agent-123.domain.com/rpc")
    print()
    print("  # Discovery workflow")
    print("  1. List agents: GET /v1/agents/")
    print("  2. Get agent well-known: GET /v1/agents/{id}/.well-known/agent.json")
    print("  3. Communicate: POST /v1/agents/{id}/rpc")
    print("  4. Future: Direct subdomain access")

if __name__ == "__main__":
    success = validate_agent_well_known()
    
    if success:
        print("\n🎉 Agent-Specific Well-Known Endpoints Validation PASSED!")
        show_agent_well_known_structure()
        show_proxy_examples()
        print("\n🚀 Ready for per-agent discovery and future subdomain proxy!")
    else:
        print("\n❌ Agent-Specific Well-Known Endpoints Validation FAILED!")
        print("Please check the implementation and fix any issues.")