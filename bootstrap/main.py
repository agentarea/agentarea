#!/usr/bin/env python3

import sys
import os

# Add the current directory to Python path so we can import from code/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from code.populate_llm_providers import main as populate_llm_providers_main
from code.minio_setup import minio_setup
from code.infisical_setup import infisical_setup

def main():
    print("Starting AgentArea Bootstrap Process...")
    print("Note: This runs after database migrations have completed")
    print("=" * 50)
    
    try:
        print("1. Setting up MinIO...")
        minio_setup()
        print("✓ MinIO setup completed")
        
        print("\n2. Setting up Infisical (including database creation)...")
        infisical_setup()
        print("✓ Infisical setup completed")
        
        print("\n3. Populating LLM providers and models...")
        populate_llm_providers_main()
        print("✓ LLM providers populated")
        
        print("\n" + "=" * 50)
        print("Bootstrap process completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Bootstrap failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
