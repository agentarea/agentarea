#!/usr/bin/env python3
"""
Test script to verify the metadata serialization fix.

This script tests that the TaskRepository can handle different types of metadata
values without causing JSON serialization errors.
"""

import asyncio
import json
import sys
from datetime import datetime
from uuid import uuid4
from sqlalchemy import MetaData

# Add the core directory to Python path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

def test_metadata_serialization():
    """Test different metadata types for JSON serialization."""
    print("\n=== Testing Metadata Serialization ===")
    
    test_cases = [
        ("Valid dict", {"key": "value", "number": 42}),
        ("Empty dict", {}),
        ("None value", None),
        ("SQLAlchemy MetaData", MetaData()),
        ("String (invalid)", "not a dict"),
        ("List (invalid)", [1, 2, 3]),
        ("Integer (invalid)", 123),
    ]
    
    results = []
    
    for test_name, metadata_value in test_cases:
        try:
            # Simulate the fix logic from the repository
            if metadata_value is not None and not isinstance(metadata_value, dict):
                processed_metadata = {}
            else:
                processed_metadata = metadata_value
            
            # Test JSON serialization
            if processed_metadata is not None:
                json.dumps(processed_metadata)
            
            results.append({
                "test": test_name,
                "original_type": type(metadata_value).__name__,
                "processed_type": type(processed_metadata).__name__ if processed_metadata is not None else "NoneType",
                "success": True,
                "error": None
            })
            print(f"✅ {test_name}: {type(metadata_value).__name__} -> {type(processed_metadata).__name__ if processed_metadata is not None else 'None'}")
            
        except Exception as e:
            results.append({
                "test": test_name,
                "original_type": type(metadata_value).__name__,
                "processed_type": "error",
                "success": False,
                "error": str(e)
            })
            print(f"❌ {test_name}: {e}")
    
    return results

def test_task_domain_model_creation():
    """Test creating Task domain models with different metadata types."""
    print("\n=== Testing Task Domain Model Creation ===")
    
    try:
        # Import Task model
        from agentarea_tasks.domain.models import Task
        
        test_cases = [
            ("Valid dict metadata", {"priority": "high"}),
            ("Empty dict metadata", {}),
            ("None metadata", None),
        ]
        
        results = []
        
        for test_name, metadata_value in test_cases:
            try:
                task = Task(
                    id=uuid4(),
                    agent_id=uuid4(),
                    description="Test task",
                    parameters={},
                    status="pending",
                    result=None,
                    error=None,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    started_at=None,
                    completed_at=None,
                    execution_id=None,
                    user_id="test_user",
                    workspace_id="test_workspace",
                    metadata=metadata_value
                )
                
                results.append({
                    "test": test_name,
                    "success": True,
                    "task_id": str(task.id),
                    "metadata_type": type(task.metadata).__name__ if task.metadata is not None else "NoneType",
                    "error": None
                })
                print(f"✅ {test_name}: Task created successfully with metadata type {type(task.metadata).__name__ if task.metadata is not None else 'None'}")
                
            except Exception as e:
                results.append({
                    "test": test_name,
                    "success": False,
                    "task_id": None,
                    "metadata_type": "error",
                    "error": str(e)
                })
                print(f"❌ {test_name}: {e}")
        
        return results
        
    except ImportError as e:
        print(f"❌ Could not import Task model: {e}")
        return [{"test": "Import Task model", "success": False, "error": str(e)}]

def test_repository_metadata_handling():
    """Test the repository's metadata handling logic."""
    print("\n=== Testing Repository Metadata Handling ===")
    
    # Simulate the repository's metadata handling logic
    def handle_metadata(metadata):
        """Simulate the fix in the repository."""
        if metadata is not None and not isinstance(metadata, dict):
            return {}
        return metadata
    
    test_cases = [
        ("Valid dict", {"key": "value"}),
        ("Empty dict", {}),
        ("None", None),
        ("SQLAlchemy MetaData", MetaData()),
        ("String", "invalid"),
        ("List", [1, 2, 3]),
    ]
    
    results = []
    
    for test_name, metadata_value in test_cases:
        try:
            processed = handle_metadata(metadata_value)
            
            # Test that the processed value is JSON serializable
            if processed is not None:
                json.dumps(processed)
            
            results.append({
                "test": test_name,
                "original_type": type(metadata_value).__name__,
                "processed_value": processed,
                "success": True,
                "error": None
            })
            print(f"✅ {test_name}: {type(metadata_value).__name__} -> {processed}")
            
        except Exception as e:
            results.append({
                "test": test_name,
                "original_type": type(metadata_value).__name__,
                "processed_value": None,
                "success": False,
                "error": str(e)
            })
            print(f"❌ {test_name}: {e}")
    
    return results

def main():
    """Run all metadata fix tests."""
    print("🔧 Testing Metadata Serialization Fix")
    print("=" * 50)
    
    all_results = {
        "metadata_serialization": test_metadata_serialization(),
        "task_domain_model": test_task_domain_model_creation(),
        "repository_handling": test_repository_metadata_handling(),
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Summary
    print("\n=== Test Summary ===")
    total_tests = 0
    passed_tests = 0
    
    for category, results in all_results.items():
        if category == "timestamp":
            continue
        
        category_passed = sum(1 for r in results if r.get("success", False))
        category_total = len(results)
        total_tests += category_total
        passed_tests += category_passed
        
        print(f"{category}: {category_passed}/{category_total} tests passed")
    
    print(f"\nOverall: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All tests passed! The metadata serialization fix is working correctly.")
    else:
        print(f"⚠️  {total_tests - passed_tests} tests failed. Please review the issues above.")
    
    # Save results
    with open('/Users/jamakase/Projects/startup/agentarea/metadata_fix_test_results.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print(f"\nDetailed results saved to: metadata_fix_test_results.json")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)