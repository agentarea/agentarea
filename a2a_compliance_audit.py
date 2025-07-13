#!/usr/bin/env python3
"""A2A Protocol Compliance Audit

Checks our implementation against the official A2A specification requirements.
"""

import os
import json
import re
from typing import Dict, List, Any

def audit_agent_card_compliance():
    """Audit Agent Card implementation against A2A spec."""
    print("🔍 Agent Card Compliance Audit")
    print("=" * 40)
    
    issues = []
    
    # Check well_known.py implementation
    well_known_path = "core/apps/api/agentarea_api/api/v1/well_known.py"
    agents_well_known_path = "core/apps/api/agentarea_api/api/v1/agents_well_known.py"
    
    for file_path, file_name in [(well_known_path, "well_known.py"), (agents_well_known_path, "agents_well_known.py")]:
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r') as f:
            content = f.read()
        
        print(f"\n📋 Checking {file_name}:")
        
        # Required fields check
        required_fields = {
            "name": "agent.name",
            "description": "agent.description", 
            "url": "url=",
            "version": 'version="',
            "capabilities": "AgentCapabilities",
            "provider": "AgentProvider",
            "skills": "AgentSkill"
        }
        
        for field, pattern in required_fields.items():
            if pattern in content:
                print(f"  ✅ {field}: Found")
            else:
                print(f"  ❌ {field}: Missing or incorrect")
                issues.append(f"{file_name}: Missing {field}")
        
        # Check for optional but recommended fields
        optional_fields = {
            "documentationUrl": "documentationUrl",
            "defaultInputModes": "inputModes", 
            "defaultOutputModes": "outputModes"
        }
        
        print(f"  📝 Optional fields in {file_name}:")
        for field, pattern in optional_fields.items():
            if pattern in content:
                print(f"    ✅ {field}: Found")
            else:
                print(f"    ⚠️  {field}: Missing (optional)")
    
    return issues

def audit_message_format_compliance():
    """Audit Message format implementation."""
    print("\n🔍 Message Format Compliance Audit")
    print("=" * 40)
    
    issues = []
    
    # Check types.py for proper message structures
    common_types_files = [
        "core/libs/common/agentarea_common/utils/types.py"
    ]
    
    for file_path in common_types_files:
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Required message components
        message_requirements = {
            "Message class": "class Message",
            "TextPart": "TextPart",
            "role field": "role:",
            "parts field": "parts:",
            "FilePart support": "FilePart",
            "DataPart support": "DataPart"
        }
        
        for requirement, pattern in message_requirements.items():
            if pattern in content:
                print(f"  ✅ {requirement}: Found")
            else:
                print(f"  ❌ {requirement}: Missing")
                if "Part" in requirement and requirement != "parts field":
                    issues.append(f"Missing {requirement} in message format")
    
    return issues

def audit_task_management_compliance():
    """Audit Task management implementation."""
    print("\n🔍 Task Management Compliance Audit")
    print("=" * 40)
    
    issues = []
    
    # Check A2A endpoints implementation
    a2a_files = [
        "core/apps/api/agentarea_api/api/v1/agents_a2a.py"
    ]
    
    for file_path in a2a_files:
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Required A2A methods per spec
        required_methods = {
            "message/send": "message/send",  # Note: spec uses tasks/send, but message/send is common
            "message/stream": "message/stream",
            "tasks/get": "tasks/get", 
            "tasks/cancel": "tasks/cancel",
            "agent/authenticatedExtendedCard": "agent/authenticatedExtendedCard"
        }
        
        for method, pattern in required_methods.items():
            if pattern in content:
                print(f"  ✅ Method {method}: Implemented")
            else:
                print(f"  ❌ Method {method}: Missing")
                issues.append(f"Missing required method: {method}")
        
        # Check for proper task parameters
        task_params = {
            "task id": "id",
            "message": "message",
            "sessionId": "sessionId"
        }
        
        print("  📋 Task Parameters:")
        for param, pattern in task_params.items():
            if pattern in content:
                print(f"    ✅ {param}: Found")
            else:
                print(f"    ⚠️  {param}: Check implementation")
    
    return issues

def find_mocks_and_hardcoded_values():
    """Find mock implementations and hardcoded values that should be removed."""
    print("\n🔍 Mock Detection Audit")
    print("=" * 40)
    
    mock_patterns = [
        ("demo", r"demo[_-]?agent", "Demo agent references"),
        ("test", r"test[_-]?[a-z]+", "Test-related code"),
        ("mock", r"mock[_-]?[a-z]+", "Mock implementations"),
        ("hardcoded", r"localhost:8000", "Hardcoded localhost URLs"),
        ("placeholder", r"placeholder|TODO|FIXME", "Placeholder code"),
        ("example", r"example\.com", "Example domains")
    ]
    
    files_to_check = []
    
    # Find all Python files in API
    for root, dirs, files in os.walk("core/apps/api"):
        for file in files:
            if file.endswith('.py'):
                files_to_check.append(os.path.join(root, file))
    
    mocks_found = []
    
    for file_path in files_to_check:
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                lines = content.split('\n')
            
            for line_num, line in enumerate(lines, 1):
                for pattern_name, pattern, description in mock_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        relative_path = file_path.replace("core/apps/api/", "")
                        mocks_found.append({
                            "file": relative_path,
                            "line": line_num,
                            "content": line.strip(),
                            "type": description,
                            "pattern": pattern_name
                        })
        except Exception as e:
            continue
    
    # Group by type
    mock_groups = {}
    for mock in mocks_found:
        mock_type = mock["type"]
        if mock_type not in mock_groups:
            mock_groups[mock_type] = []
        mock_groups[mock_type].append(mock)
    
    for mock_type, mocks in mock_groups.items():
        print(f"\n  📋 {mock_type}:")
        for mock in mocks[:5]:  # Show first 5 of each type
            print(f"    📁 {mock['file']}:{mock['line']}")
            print(f"       {mock['content'][:80]}...")
        
        if len(mocks) > 5:
            print(f"    ... and {len(mocks) - 5} more")
    
    return mocks_found

def audit_json_rpc_compliance():
    """Audit JSON-RPC 2.0 compliance."""
    print("\n🔍 JSON-RPC 2.0 Compliance Audit")
    print("=" * 40)
    
    issues = []
    
    # Check validation implementation
    validation_file = "core/apps/api/agentarea_api/api/v1/a2a_validation.py"
    
    if os.path.exists(validation_file):
        with open(validation_file, 'r') as f:
            content = f.read()
        
        jsonrpc_requirements = {
            "jsonrpc field": '"jsonrpc": "2.0"',
            "method field": '"method"',
            "id field": '"id"',
            "params field": '"params"',
            "result field": '"result"',
            "error field": '"error"',
            "error codes": "error_code_mapping"
        }
        
        for requirement, pattern in jsonrpc_requirements.items():
            if pattern in content:
                print(f"  ✅ {requirement}: Implemented")
            else:
                print(f"  ❌ {requirement}: Missing")
                issues.append(f"JSON-RPC: Missing {requirement}")
    else:
        print("  ❌ Validation file not found")
        issues.append("Missing a2a_validation.py")
    
    return issues

def check_authentication_compliance():
    """Check authentication implementation compliance."""
    print("\n🔍 Authentication Compliance Audit")
    print("=" * 40)
    
    issues = []
    
    auth_file = "core/apps/api/agentarea_api/api/v1/a2a_auth.py"
    
    if os.path.exists(auth_file):
        with open(auth_file, 'r') as f:
            content = f.read()
        
        auth_requirements = {
            "Bearer token": "Bearer",
            "API Key": "X-API-Key",
            "OpenAPI auth schemes": "HTTPBearer",
            "Authentication context": "A2AAuthContext",
            "Permission system": "A2APermissions"
        }
        
        for requirement, pattern in auth_requirements.items():
            if pattern in content:
                print(f"  ✅ {requirement}: Implemented")
            else:
                print(f"  ⚠️  {requirement}: Check implementation")
    else:
        print("  ❌ Authentication file not found")
        issues.append("Missing a2a_auth.py")
    
    return issues

def generate_compliance_report():
    """Generate complete compliance report."""
    print("🎯 A2A Protocol Compliance Audit Report")
    print("=" * 60)
    
    all_issues = []
    
    # Run all audits
    all_issues.extend(audit_agent_card_compliance())
    all_issues.extend(audit_message_format_compliance())
    all_issues.extend(audit_task_management_compliance())
    all_issues.extend(audit_json_rpc_compliance())
    all_issues.extend(check_authentication_compliance())
    
    mocks = find_mocks_and_hardcoded_values()
    
    # Summary
    print("\n📊 COMPLIANCE SUMMARY")
    print("=" * 30)
    
    if not all_issues:
        print("✅ No major compliance issues found!")
    else:
        print(f"⚠️  Found {len(all_issues)} compliance issues:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    
    print(f"\n🔧 Found {len(mocks)} potential mock/hardcoded values to review")
    
    # Critical missing features
    print("\n🚨 CRITICAL MISSING FEATURES")
    print("=" * 30)
    
    critical_missing = []
    
    # Check for tasks/send method (A2A spec uses tasks/send, not message/send)
    a2a_file = "core/apps/api/agentarea_api/api/v1/agents_a2a.py"
    if os.path.exists(a2a_file):
        with open(a2a_file, 'r') as f:
            content = f.read()
        
        if "tasks/send" not in content:
            critical_missing.append("tasks/send method (A2A spec requires this instead of message/send)")
        
        if "FilePart" not in content:
            critical_missing.append("FilePart support in messages")
        
        if "DataPart" not in content:
            critical_missing.append("DataPart support in messages")
    
    if critical_missing:
        for feature in critical_missing:
            print(f"  ❌ {feature}")
    else:
        print("  ✅ No critical missing features")
    
    return all_issues, mocks, critical_missing

if __name__ == "__main__":
    issues, mocks, critical = generate_compliance_report()
    
    print(f"\n🎯 NEXT STEPS:")
    print("=" * 15)
    print("1. Fix critical missing features")
    print("2. Address compliance issues")
    print("3. Review and remove unnecessary mocks")
    print("4. Add missing optional features for better compatibility")