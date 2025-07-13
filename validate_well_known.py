#!/usr/bin/env python3
"""Validate well-known endpoints implementation."""

import os
import re

def validate_well_known_endpoints():
    """Validate that well-known endpoints are properly implemented."""
    
    print("🔍 Validating A2A Well-Known Endpoints")
    print("=" * 50)
    
    # 1. Check that well_known.py exists
    well_known_path = "core/apps/api/agentarea_api/api/v1/well_known.py"
    if os.path.exists(well_known_path):
        print("✅ Well-known endpoints file exists: well_known.py")
    else:
        print("❌ Missing well-known endpoints file: well_known.py")
        return False
    
    # 2. Check that well_known.py has the expected endpoints
    with open(well_known_path, 'r') as f:
        content = f.read()
    
    expected_endpoints = [
        '@router.get("/agent.json")',
        '@router.get("/agents.json")',
        '@router.get("/a2a-info.json")',
        '@router.get("/")',
        'get_default_agent_card',
        'get_agent_registry',
        'get_a2a_info',
        'well_known_index',
        'prefix="/.well-known"'
    ]
    
    for endpoint in expected_endpoints:
        if endpoint in content:
            print(f"✅ Found expected endpoint/function: {endpoint}")
        else:
            print(f"❌ Missing endpoint/function: {endpoint}")
            return False
    
    # 3. Check that main.py includes well-known router
    main_path = "core/apps/api/agentarea_api/main.py"
    if os.path.exists(main_path):
        with open(main_path, 'r') as f:
            main_content = f.read()
        
        if "well_known import router as well_known_router" in main_content:
            print("✅ main.py imports well-known router")
        else:
            print("❌ main.py missing well-known router import")
            return False
        
        if "app.include_router(well_known_router)" in main_content:
            print("✅ main.py includes well-known router at root level")
        else:
            print("❌ main.py missing well-known router inclusion")
            return False
    
    # 4. Check that well-known router has correct prefix
    if 'prefix="/.well-known"' in content:
        print("✅ Well-known router has correct prefix: /.well-known")
    else:
        print("❌ Well-known router missing correct prefix")
        return False
    
    return True

def show_well_known_structure():
    """Show the new well-known URL structure."""
    print("\n📋 A2A Well-Known URL Structure:")
    print("  /.well-known/agent.json      - Single agent discovery (RFC 8615)")
    print("  /.well-known/agents.json     - Multi-agent registry (custom)")
    print("  /.well-known/a2a-info.json   - A2A protocol info")
    print("  /.well-known/                - Well-known endpoints index")
    
    print("\n🔄 Complete A2A Discovery Flow:")
    print("  1. /.well-known/agent.json   - Discover default agent")
    print("  2. /.well-known/agents.json  - Discover all agents")
    print("  3. /v1/agents/{id}/card      - Get specific agent card")
    print("  4. /v1/agents/{id}/rpc       - Communicate with agent")
    
    print("\n✅ Benefits of well-known endpoints:")
    print("  • Standard RFC 8615 compliance")
    print("  • Automatic discovery by crawlers")
    print("  • Reduces discovery to domain resolution")
    print("  • Works with existing A2A tooling")
    print("  • Supports both single and multi-agent scenarios")

def show_usage_examples():
    """Show usage examples for well-known endpoints."""
    print("\n💡 Usage Examples:")
    print("  # Discover default agent")
    print("  curl https://yourapp.com/.well-known/agent.json")
    print()
    print("  # Discover specific agent")
    print("  curl 'https://yourapp.com/.well-known/agent.json?agent_id=123'")
    print()
    print("  # Get agent registry")
    print("  curl 'https://yourapp.com/.well-known/agents.json?limit=5'")
    print()
    print("  # Get A2A protocol info")
    print("  curl https://yourapp.com/.well-known/a2a-info.json")
    print()
    print("  # Communicate with discovered agent")
    print("  curl -X POST https://yourapp.com/v1/agents/123/rpc \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -d '{\"jsonrpc\":\"2.0\",\"method\":\"message/send\",\"params\":{...}}'")

if __name__ == "__main__":
    success = validate_well_known_endpoints()
    
    if success:
        print("\n🎉 Well-Known Endpoints Validation PASSED!")
        show_well_known_structure()
        show_usage_examples()
        print("\n🚀 Ready to discover agents via standard A2A well-known endpoints!")
    else:
        print("\n❌ Well-Known Endpoints Validation FAILED!")
        print("Please check the implementation and fix any issues.")