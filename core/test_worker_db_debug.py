#!/usr/bin/env python3
"""
Debug script to test worker database configuration.
"""
import asyncio
import sys
import os

# Add the core directory to the path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

from agentarea_common.config import get_database, get_settings


async def test_worker_db_config():
    """Test worker database configuration."""
    print("🔍 Testing worker database configuration...")
    
    # Print environment variables
    print("\n📋 Database environment variables:")
    db_vars = ['POSTGRES_HOST', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'DATABASE_URL']
    for var in db_vars:
        value = os.getenv(var, 'NOT SET')
        if 'PASSWORD' in var and value != 'NOT SET':
            value = '***'  # Hide password
        print(f"   {var}: {value}")
    
    # Test settings
    print("\n⚙️ Testing settings...")
    try:
        settings = get_settings()
        print(f"✅ Settings loaded successfully")
        print(f"   Database URL: {settings.database.url[:50]}...")  # Show first 50 chars
    except Exception as e:
        print(f"❌ Settings loading failed: {e}")
        return
    
    # Test database connection
    print("\n🔌 Testing database connection...")
    try:
        database = get_database()
        async with database.async_session_factory() as session:
            print("✅ Database connection successful")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n🎉 Worker database configuration test completed!")


if __name__ == "__main__":
    asyncio.run(test_worker_db_config())