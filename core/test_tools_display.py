#!/usr/bin/env python3
"""
Test script to simulate agent data with different tool configurations
"""

import json

# Simulate different agent configurations
test_agents = [
    {
        "id": "agent-1",
        "name": "Calculator Agent",
        "description": "Agent with calculator tool",
        "tools_config": {
            "mcp_server_configs": [],
            "builtin_tools": [
                {"tool_name": "calculator", "requires_user_confirmation": False, "enabled": True}
            ]
        }
    },
    {
        "id": "agent-2", 
        "name": "MCP Agent",
        "description": "Agent with MCP servers",
        "tools_config": {
            "mcp_server_configs": [
                {"mcp_server_id": "github-server-uuid", "allowed_tools": []},
                {"mcp_server_id": "jira-server-uuid", "allowed_tools": []}
            ],
            "builtin_tools": []
        }
    },
    {
        "id": "agent-3",
        "name": "Mixed Tools Agent", 
        "description": "Agent with both builtin and MCP tools",
        "tools_config": {
            "mcp_server_configs": [
                {"mcp_server_id": "notion-server-uuid", "allowed_tools": []}
            ],
            "builtin_tools": [
                {"tool_name": "calculator", "requires_user_confirmation": False, "enabled": True},
                {"tool_name": "weather", "requires_user_confirmation": False, "enabled": True}
            ]
        }
    },
    {
        "id": "agent-4",
        "name": "No Tools Agent",
        "description": "Agent without any tools",
        "tools_config": {
            "mcp_server_configs": [],
            "builtin_tools": []
        }
    },
    {
        "id": "agent-5", 
        "name": "Null Tools Agent",
        "description": "Agent with null tools_config",
        "tools_config": None
    }
]

print("=== Testing Tools Display Logic ===\n")

for agent in test_agents:
    print(f"Agent: {agent['name']}")
    print(f"Tools Config: {json.dumps(agent['tools_config'], indent=2) if agent['tools_config'] else 'None'}")
    
    # Simulate what the frontend function would do
    tools_config = agent.get('tools_config')
    tool_count = 0
    
    if tools_config:
        builtin_count = len(tools_config.get('builtin_tools', []))
        mcp_count = len(tools_config.get('mcp_server_configs', []))
        tool_count = builtin_count + mcp_count
        
        if tool_count > 0:
            print(f"Expected display: {builtin_count} builtin + {mcp_count} MCP = {tool_count} tool avatars")
        else:
            print("Expected display: 'No tools' text")
    else:
        print("Expected display: 'No tools' text")
    
    print("-" * 40)

print("\n✅ Tools display test completed!")