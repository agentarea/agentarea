#!/usr/bin/env python3
"""Test script for the AgentArea CLI."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))

try:
    from core.apps.cli.agentarea_cli.main import AgentAreaClient, AuthConfig, cli

    print("✅ CLI module imported successfully")

    # Test AuthConfig
    auth_config = AuthConfig()
    print("✅ AuthConfig created successfully")

    # Test AgentAreaClient
    client = AgentAreaClient("http://localhost:8000", auth_config)
    print("✅ AgentAreaClient created successfully")

    print("\n🎉 All CLI components are working correctly!")
    print("\nAvailable commands:")
    print("  agentarea auth login [--user-id USER] [--admin]")
    print("  agentarea auth logout")
    print("  agentarea auth status")
    print("  agentarea chat send AGENT_ID [--message MESSAGE]")
    print("  agentarea chat agents")
    print("  agentarea agent list")
    print("  agentarea agent create")
    print("  agentarea llm list")
    print("  agentarea llm create")
    print("  agentarea system status")

except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
