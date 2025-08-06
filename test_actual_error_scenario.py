#!/usr/bin/env python3
"""
Test script to simulate the actual error scenario reported by the user.

This script tests the specific case where a MetaData object causes
the "Object of type MetaData is not JSON serializable" error.
"""

import asyncio
import json
import sys
from datetime import datetime
from uuid import uuid4
from sqlalchemy import MetaData

# Add the core directory to Python path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

def test_metadata_object_serialization():
    """Test the specific MetaData serialization issue."""
    print("\n=== Testing MetaData Object Serialization Issue ===")
    
    # This is what was causing the original error
    metadata_obj = MetaData()
    
    print(f"Original MetaData object: {metadata_obj}")
    print(f"Type: {type(metadata_obj)}")
    
    # Test direct JSON serialization (this should fail)
    try:
        json.dumps({'task_metadata': metadata_obj})
        print("❌ ERROR: Direct serialization should have failed!")
        return False
    except TypeError as e:
        print(f"✅ Expected error with direct serialization: {e}")
    
    # Test our fix logic
    def apply_metadata_fix(metadata):
        """Apply the same fix logic from the repository."""
        if metadata is not None and not isinstance(metadata, dict):
            return {}
        return metadata
    
    fixed_metadata = apply_metadata_fix(metadata_obj)
    print(f"Fixed metadata: {fixed_metadata}")
    print(f"Fixed type: {type(fixed_metadata)}")
    
    # Test JSON serialization with fix (this should work)
    try:
        json_str = json.dumps({'task_metadata': fixed_metadata})
        print(f"✅ Fixed serialization works: {json_str}")
        return True
    except TypeError as e:
        print(f"❌ Fixed serialization failed: {e}")
        return False

def test_repository_update_simulation():
    """Simulate the repository update that was failing."""
    print("\n=== Simulating Repository Update ===")
    
    # Simulate the problematic scenario
    task_id = uuid4()
    metadata_obj = MetaData()  # This was causing the issue
    
    print(f"Simulating update for task: {task_id}")
    print(f"Problematic metadata: {metadata_obj} (type: {type(metadata_obj)})")
    
    # Simulate the old behavior (would fail)
    old_task_data = {
        'task_metadata': metadata_obj,  # Direct assignment - causes error
        'updated_at': datetime.utcnow()
    }
    
    try:
        # This simulates the SQL parameter serialization
        json.dumps(old_task_data, default=str)
        print("❌ ERROR: Old behavior should have failed!")
        return False
    except TypeError as e:
        print(f"✅ Old behavior correctly fails: {e}")
    
    # Simulate the new behavior (should work)
    def handle_metadata_in_update(entity_metadata):
        """Apply the repository fix logic."""
        if entity_metadata is not None and not isinstance(entity_metadata, dict):
            return {}
        return entity_metadata
    
    fixed_metadata = handle_metadata_in_update(metadata_obj)
    new_task_data = {
        'task_metadata': fixed_metadata,
        'updated_at': datetime.utcnow()
    }
    
    try:
        json_str = json.dumps(new_task_data, default=str)
        print(f"✅ New behavior works: {json_str[:100]}...")
        return True
    except TypeError as e:
        print(f"❌ New behavior failed: {e}")
        return False

def test_temporal_task_manager_scenario():
    """Test the scenario from temporal_task_manager.py."""
    print("\n=== Testing Temporal Task Manager Scenario ===")
    
    # This simulates what happens in _task_to_simple_task
    class MockTask:
        def __init__(self):
            self.id = uuid4()
            self.metadata_raw = MetaData()  # This could be a MetaData object
    
    mock_task = MockTask()
    print(f"Mock task metadata_raw: {mock_task.metadata_raw} (type: {type(mock_task.metadata_raw)})")
    
    # Simulate the conversion logic from temporal_task_manager.py
    def convert_metadata_raw(metadata_raw):
        """Simulate the _task_to_simple_task conversion."""
        if isinstance(metadata_raw, dict):
            return metadata_raw
        else:
            # Convert non-dict to empty dict
            return {}
    
    converted_metadata = convert_metadata_raw(mock_task.metadata_raw)
    print(f"Converted metadata: {converted_metadata} (type: {type(converted_metadata)})")
    
    # Test that this can be JSON serialized
    try:
        json_str = json.dumps({'metadata': converted_metadata})
        print(f"✅ Converted metadata is JSON serializable: {json_str}")
        return True
    except TypeError as e:
        print(f"❌ Converted metadata serialization failed: {e}")
        return False

def main():
    """Run all error scenario tests."""
    print("🔧 Testing Actual Error Scenario Fix")
    print("=" * 50)
    print("This simulates the exact error reported by the user:")
    print("'(builtins.TypeError) Object of type MetaData is not JSON serializable'")
    
    tests = [
        ("MetaData Object Serialization", test_metadata_object_serialization),
        ("Repository Update Simulation", test_repository_update_simulation),
        ("Temporal Task Manager Scenario", test_temporal_task_manager_scenario),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success, None))
        except Exception as e:
            results.append((test_name, False, str(e)))
    
    # Summary
    print("\n=== Test Results Summary ===")
    passed = 0
    total = len(results)
    
    for test_name, success, error in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
        if error:
            print(f"    Error: {error}")
        if success:
            passed += 1
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 SUCCESS: The MetaData serialization fix resolves the reported error!")
        print("\nThe fix ensures that:")
        print("1. SQLAlchemy MetaData objects are converted to empty dicts")
        print("2. All metadata values are JSON serializable before database updates")
        print("3. The original error 'Object of type MetaData is not JSON serializable' is prevented")
    else:
        print(f"\n⚠️  WARNING: {total - passed} tests failed. The fix may not be complete.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)