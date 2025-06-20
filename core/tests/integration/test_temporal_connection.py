#!/usr/bin/env python3
import asyncio
import logging
from temporalio.client import Client

logging.basicConfig(level=logging.DEBUG)

async def test_simple_connection():
    try:
        print("Attempting to connect to localhost:7233 with default settings...")
        # Try with explicit namespace
        client = await Client.connect("localhost:7233", namespace="default")
        print("✅ Basic connection successful!")
        
        # Test basic operation
        workflows = await client.list_workflows()
        print(f"✅ Listed workflows successfully: {len(workflows)} workflows found")
        
        await client.close()
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_minimal_connection():
    try:
        print("\nTrying minimal connection without namespace...")
        client = await Client.connect("localhost:7233")
        print("✅ Minimal connection successful!")
        
        await client.close()
        return True
        
    except Exception as e:
        print(f"❌ Minimal connection failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing Temporal connections...")
    
    success1 = asyncio.run(test_simple_connection())
    success2 = asyncio.run(test_minimal_connection())
    
    if success1 or success2:
        print("\n✅ At least one connection method worked!")
    else:
        print("\n❌ All connection attempts failed!")
        print("\nThis suggests a configuration or compatibility issue.")
        print("Recommendations:")
        print("1. Check if Temporal server is fully started and ready")
        print("2. Try connecting with temporal CLI: 'temporal workflow list'")
        print("3. Check server logs for any connection errors") 