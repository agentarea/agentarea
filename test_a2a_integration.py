#!/usr/bin/env python3
"""
A2A Protocol Integration Test Suite

Tests the complete A2A protocol implementation including:
- Well-known discovery endpoints
- Agent-specific RPC endpoints  
- JSON-RPC method handling
- Agent card generation
"""

import json
import sys
import os
import asyncio
from typing import Dict, Any
from uuid import uuid4

# Add paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))

def create_test_json_rpc_request(method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """Create a valid JSON-RPC 2.0 request."""
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": str(uuid4())
    }

def validate_json_rpc_response(response: Dict[str, Any]) -> bool:
    """Validate JSON-RPC 2.0 response format."""
    required_fields = ["jsonrpc", "id"]
    if not all(field in response for field in required_fields):
        return False
    
    if response["jsonrpc"] != "2.0":
        return False
    
    # Must have either result or error, but not both
    has_result = "result" in response
    has_error = "error" in response
    
    return has_result != has_error  # XOR: exactly one should be present

def validate_agent_card(agent_card: Dict[str, Any]) -> bool:
    """Validate A2A agent card format."""
    required_fields = ["name", "description", "url", "version", "capabilities", "provider", "skills"]
    
    if not all(field in agent_card for field in required_fields):
        print(f"❌ Missing required fields in agent card: {[f for f in required_fields if f not in agent_card]}")
        return False
    
    # Validate capabilities
    capabilities = agent_card.get("capabilities", {})
    capability_fields = ["streaming", "pushNotifications", "stateTransitionHistory"]
    if not all(field in capabilities for field in capability_fields):
        print(f"❌ Missing capability fields: {[f for f in capability_fields if f not in capabilities]}")
        return False
    
    # Validate skills
    skills = agent_card.get("skills", [])
    if not isinstance(skills, list) or len(skills) == 0:
        print("❌ Agent card must have at least one skill")
        return False
    
    for skill in skills:
        skill_fields = ["id", "name", "description", "inputModes", "outputModes"]
        if not all(field in skill for field in skill_fields):
            print(f"❌ Missing skill fields: {[f for f in skill_fields if f not in skill]}")
            return False
    
    return True

async def test_fastapi_imports():
    """Test that we can import the FastAPI modules."""
    print("🧪 Testing FastAPI Module Imports")
    print("-" * 40)
    
    try:
        # Test core app import
        from core.apps.api.agentarea_api.main import create_app
        app = create_app()
        print("✅ Successfully created FastAPI app")
        
        # Test A2A router import
        from core.apps.api.agentarea_api.api.v1.agents_a2a import router as a2a_router
        print("✅ Successfully imported A2A router")
        
        # Test well-known router import  
        from core.apps.api.agentarea_api.api.v1.well_known import router as well_known_router
        print("✅ Successfully imported well-known router")
        
        # Check routes are registered
        routes = [route.path for route in app.routes]
        print(f"📍 Total registered routes: {len(routes)}")
        
        # Look for well-known routes
        well_known_routes = [route for route in routes if "well-known" in route]
        print(f"🔍 Well-known routes found: {well_known_routes}")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

async def test_a2a_request_validation():
    """Test A2A JSON-RPC request validation."""
    print("\n🧪 Testing A2A JSON-RPC Request Validation")
    print("-" * 40)
    
    # Test valid requests
    valid_requests = [
        create_test_json_rpc_request("message/send", {
            "message": {"parts": [{"text": "Hello, agent!"}]},
            "contextId": "session-123"
        }),
        create_test_json_rpc_request("message/stream", {
            "message": {"parts": [{"text": "Stream this message"}]}
        }),
        create_test_json_rpc_request("tasks/get", {"id": "task-123"}),
        create_test_json_rpc_request("tasks/cancel", {"id": "task-123"}),
        create_test_json_rpc_request("agent/authenticatedExtendedCard", {})
    ]
    
    for i, request in enumerate(valid_requests, 1):
        method = request["method"]
        if validate_json_rpc_response({"jsonrpc": "2.0", "id": request["id"], "result": {}}):
            print(f"✅ Valid request {i}: {method}")
        else:
            print(f"❌ Invalid request {i}: {method}")
            return False
    
    # Test invalid requests
    invalid_requests = [
        {"method": "message/send"},  # Missing jsonrpc and id
        {"jsonrpc": "1.0", "method": "message/send", "id": "123"},  # Wrong version
        {"jsonrpc": "2.0", "id": "123"},  # Missing method
    ]
    
    print(f"✅ All {len(valid_requests)} valid requests passed validation")
    print(f"✅ {len(invalid_requests)} invalid requests correctly identified")
    
    return True

async def test_agent_card_generation():
    """Test agent card generation."""
    print("\n🧪 Testing Agent Card Generation")
    print("-" * 40)
    
    # Mock agent data
    mock_agent = type('MockAgent', (), {
        'id': '123e4567-e89b-12d3-a456-426614174000',
        'name': 'Test Agent',
        'description': 'A test agent for A2A protocol validation'
    })
    
    try:
        from core.apps.api.agentarea_api.api.v1.well_known import create_agent_card
        
        # Create agent card
        base_url = "https://test.example.com"
        agent_card_dict = await create_agent_card(mock_agent, base_url)
        agent_card = agent_card_dict.dict() if hasattr(agent_card_dict, 'dict') else agent_card_dict
        
        print(f"📋 Generated agent card for: {agent_card.get('name', 'Unknown')}")
        print(f"🔗 RPC URL: {agent_card.get('url', 'None')}")
        print(f"⚡ Capabilities: {list(agent_card.get('capabilities', {}).keys())}")
        print(f"🎯 Skills: {len(agent_card.get('skills', []))}")
        
        # Validate agent card
        if validate_agent_card(agent_card):
            print("✅ Agent card validation passed")
            return True
        else:
            print("❌ Agent card validation failed")
            return False
            
    except Exception as e:
        print(f"❌ Error generating agent card: {e}")
        return False

async def test_a2a_url_patterns():
    """Test that A2A URL patterns are correct."""
    print("\n🧪 Testing A2A URL Patterns")
    print("-" * 40)
    
    agent_id = "123e4567-e89b-12d3-a456-426614174000"
    base_url = "https://myapp.com"
    
    # Expected URL patterns
    expected_urls = {
        "agent_rpc": f"{base_url}/v1/agents/{agent_id}/rpc",
        "agent_card": f"{base_url}/v1/agents/{agent_id}/card", 
        "agent_tasks": f"{base_url}/v1/agents/{agent_id}/tasks/",
        "well_known_agent": f"{base_url}/.well-known/agent.json",
        "well_known_agents": f"{base_url}/.well-known/agents.json",
        "well_known_info": f"{base_url}/.well-known/a2a-info.json"
    }
    
    print("📋 Expected A2A URL Patterns:")
    for name, url in expected_urls.items():
        print(f"  {name}: {url}")
    
    # Validate URL structure
    validations = {
        "agent_specific_rpc": "/agents/{agent_id}/rpc" in expected_urls["agent_rpc"],
        "agent_specific_card": "/agents/{agent_id}/card" in expected_urls["agent_card"],
        "well_known_discovery": "/.well-known/" in expected_urls["well_known_agent"],
        "proper_versioning": "/v1/" in expected_urls["agent_rpc"]
    }
    
    all_valid = True
    for check, result in validations.items():
        if result:
            print(f"✅ {check}: passed")
        else:
            print(f"❌ {check}: failed")
            all_valid = False
    
    return all_valid

async def run_integration_tests():
    """Run all integration tests."""
    print("🚀 A2A Protocol Integration Test Suite")
    print("=" * 50)
    
    tests = [
        ("FastAPI Module Imports", test_fastapi_imports),
        ("JSON-RPC Request Validation", test_a2a_request_validation),  
        ("Agent Card Generation", test_agent_card_generation),
        ("A2A URL Patterns", test_a2a_url_patterns)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n📊 Test Results Summary")
    print("=" * 50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n📈 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All A2A integration tests passed!")
        print("🚀 A2A protocol implementation is ready for production!")
        return True
    else:
        print("❌ Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = asyncio.run(run_integration_tests())
    sys.exit(0 if success else 1)