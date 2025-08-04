#!/usr/bin/env python3

import sys
import os

# Add the current directory to Python path so we can import from code/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# from code.populate_llm_providers import main as populate_llm_providers_main
from code.populate_providers_new_arch import main as populate_providers_new_arch_main
from code.populate_mcp_providers import main as populate_mcp_providers_main
from code.minio_setup import minio_setup
from code.infisical_setup import infisical_setup
from code.database_setup import database_setup


def main():
    print("Starting AgentArea Bootstrap Process...")
    print("Note: This runs after database migrations have completed")
    print("=" * 50)

    try:
        print("1. Setting up databases...")
        database_setup()
        print("✓ Database setup completed")

        print("\n2. Setting up MinIO...")
        minio_setup()
        print("✓ MinIO setup completed")

        print("\n3. Setting up Infisical (including database creation)...")
        infisical_setup()
        print("✓ Infisical setup completed")

        print("\n4. Populating provider specs and model specs (new architecture)...")
        populate_providers_new_arch_main()
        print("✓ Provider specs and model specs populated")

        print("\n5. Populating MCP server specifications...")
        populate_mcp_providers_main()
        print("✓ MCP server specifications populated")

        print("\n" + "=" * 50)
        print("Bootstrap process completed successfully!")

    except Exception as e:
        print(f"\n❌ Bootstrap failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
