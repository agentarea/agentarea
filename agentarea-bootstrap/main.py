#!/usr/bin/env python3

import sys

# from code.populate_llm_providers import main as populate_llm_providers_main
from code.populate_providers_new_arch import main as populate_providers_new_arch_main
from code.populate_mcp_providers import main as populate_mcp_providers_main
from code.populate_provider_configs import main as populate_provider_configs_main
from code.populate_default_agent import main as populate_default_agent_main
from code.populate_skills import main as populate_skills_main
from code.minio_setup import minio_setup


def main():
    print("Starting AgentArea Bootstrap Process...")
    print("Note: This runs after database migrations have completed")
    print("Note: Registry sync is now handled by `agentarea-api reconcile`")
    print("=" * 50)

    try:
        print("1. Setting up MinIO...")
        minio_setup()
        print("✓ MinIO setup completed")

        print("\n2. Populating provider specs and model specs (new architecture)...")
        populate_providers_new_arch_main()
        print("✓ Provider specs and model specs populated")

        print("\n3. Populating MCP server specifications...")
        populate_mcp_providers_main()
        print("✓ MCP server specifications populated")

        # Registry sync moved to: agentarea-api reconcile
        # This uses RegistryService as the single source of truth for parsing.
        # Run via CLI: agentarea-api reconcile --registries-config '...'

        print("\n4. Populating provider configs from Helm values...")
        populate_provider_configs_main()
        print("✓ Provider configs populated")

        print("\n5. Populating default system agent...")
        populate_default_agent_main()
        print("✓ Default agent populated")

        print("\n6. Populating system skills...")
        populate_skills_main()
        print("✓ System skills populated")

        print("\n" + "=" * 50)
        print("Bootstrap process completed successfully!")

    except Exception as e:
        print(f"\n❌ Bootstrap failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
