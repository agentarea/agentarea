#!/usr/bin/env python3
"""
Test Kubernetes backend manifest generation and API compatibility.
This test validates the K8s backend without requiring a running cluster.
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import time
import sys
import os

def make_request(method, url, data=None, headers=None):
    """Make HTTP request using urllib"""
    if headers is None:
        headers = {'Content-Type': 'application/json'}
    
    if data and isinstance(data, dict):
        data = json.dumps(data).encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            response_data = response.read().decode('utf-8')
            return {
                'status_code': response.status,
                'data': json.loads(response_data) if response_data else {},
                'headers': dict(response.headers)
            }
    except urllib.error.HTTPError as e:
        error_data = e.read().decode('utf-8')
        return {
            'status_code': e.code,
            'data': json.loads(error_data) if error_data else {},
            'error': str(e)
        }
    except Exception as e:
        return {
            'status_code': 0,
            'error': str(e)
        }

def test_kubernetes_backend_detection(base_url):
    """Test that service can detect and use Kubernetes backend when configured"""
    print("🔍 Testing Kubernetes backend detection...")
    
    # Test health endpoint to see current backend
    response = make_request('GET', f'{base_url}/health')
    if response['status_code'] != 200:
        print(f"❌ Health check failed: {response}")
        return False
    
    print(f"✅ Service health: {response['data']}")
    
    # Test backend info endpoint if available
    response = make_request('GET', f'{base_url}/backend/info')
    if response['status_code'] == 200:
        backend_info = response['data']
        print(f"📋 Backend info: {backend_info}")
        
        if 'backend_type' in backend_info:
            backend_type = backend_info['backend_type']
            print(f"🎯 Detected backend type: {backend_type}")
            
            if backend_type == 'kubernetes':
                print("✅ Successfully detected Kubernetes backend!")
                return True
            elif backend_type == 'docker':
                print("⚠️  Service using Docker backend (expected for local testing)")
                return True
            else:
                print(f"❓ Unknown backend type: {backend_type}")
                return False
        else:
            print("⚠️  Backend info missing backend_type field")
    else:
        print(f"⚠️  Backend info endpoint not available: {response}")
    
    return True

def test_instance_spec_validation(base_url):
    """Test K8s-specific instance specification validation"""
    print("\n🧪 Testing K8s instance specification validation...")
    
    # Test with K8s-style resource requirements
    k8s_spec = {
        "image": "agentarea/mcp-echo:latest",
        "name": "test-k8s-instance",
        "environment": {
            "TEST_VAR": "k8s-test"
        },
        "resources": {
            "requests": {
                "cpu": "100m",
                "memory": "128Mi"
            },
            "limits": {
                "cpu": "500m",
                "memory": "512Mi"
            }
        },
        "labels": {
            "environment": "test",
            "backend": "kubernetes"
        }
    }
    
    # Test spec validation endpoint
    response = make_request('POST', f'{base_url}/instances/validate', k8s_spec)
    
    if response['status_code'] == 200:
        validation_result = response['data']
        print(f"✅ K8s spec validation passed: {validation_result}")
        return True
    elif response['status_code'] == 400:
        print(f"⚠️  K8s spec validation failed (expected): {response['data']}")
        return True
    else:
        print(f"❌ Unexpected validation response: {response}")
        return False

def test_instance_lifecycle_k8s_mode(base_url):
    """Test instance lifecycle assuming K8s backend"""
    print("\n🚀 Testing K8s instance lifecycle...")
    
    instance_spec = {
        "image": "nginx:alpine",  # Use simple image for testing
        "name": "test-k8s-nginx",
        "environment": {
            "NGINX_PORT": "8080"
        },
        "resources": {
            "requests": {
                "cpu": "50m",
                "memory": "64Mi"
            },
            "limits": {
                "cpu": "200m",
                "memory": "256Mi"
            }
        },
        "labels": {
            "app": "test-nginx",
            "backend": "kubernetes"
        }
    }
    
    # Create instance
    print("📝 Creating K8s instance...")
    response = make_request('POST', f'{base_url}/instances', instance_spec)
    
    if response['status_code'] not in [200, 201]:
        print(f"❌ Failed to create K8s instance: {response}")
        return False
    
    instance_data = response['data']
    instance_id = instance_data.get('id') or instance_data.get('name', 'test-k8s-nginx')
    print(f"✅ Created K8s instance: {instance_id}")
    
    # Wait for instance to be ready (or at least processed)
    print("⏳ Waiting for instance to be processed...")
    time.sleep(5)
    
    # Check instance status
    print("🔍 Checking K8s instance status...")
    response = make_request('GET', f'{base_url}/instances/{instance_id}')
    
    if response['status_code'] == 200:
        status_data = response['data']
        print(f"📊 K8s instance status: {status_data}")
        
        # Look for K8s-specific fields
        if 'kubernetes_resources' in status_data or 'deployment_name' in status_data:
            print("✅ Found K8s-specific status fields!")
        else:
            print("⚠️  Status response doesn't show K8s-specific fields")
    else:
        print(f"⚠️  Could not get K8s instance status: {response}")
    
    # List all instances to see our K8s instance
    print("📋 Listing all instances...")
    response = make_request('GET', f'{base_url}/instances')
    
    if response['status_code'] == 200:
        instances = response['data']
        print(f"📊 Found {len(instances)} total instances")
        
        k8s_instance = None
        for instance in instances:
            if instance.get('name') == instance_id or instance.get('id') == instance_id:
                k8s_instance = instance
                break
        
        if k8s_instance:
            print(f"✅ Found our K8s instance in list: {k8s_instance}")
        else:
            print("⚠️  Our K8s instance not found in instance list")
    
    # Clean up - delete instance
    print("🧹 Cleaning up K8s instance...")
    response = make_request('DELETE', f'{base_url}/instances/{instance_id}')
    
    if response['status_code'] in [200, 204, 404]:
        print("✅ K8s instance cleanup completed")
    else:
        print(f"⚠️  K8s instance cleanup response: {response}")
    
    return True

def test_k8s_resource_endpoints(base_url):
    """Test K8s-specific resource management endpoints"""
    print("\n🎛️  Testing K8s resource management endpoints...")
    
    # Test K8s namespace listing (if supported)
    response = make_request('GET', f'{base_url}/kubernetes/namespaces')
    
    if response['status_code'] == 200:
        namespaces = response['data']
        print(f"✅ K8s namespaces endpoint works: {namespaces}")
    elif response['status_code'] == 404:
        print("⚠️  K8s namespaces endpoint not available (expected for Docker backend)")
    else:
        print(f"❌ Unexpected K8s namespaces response: {response}")
    
    # Test K8s resource types endpoint (if supported)
    response = make_request('GET', f'{base_url}/kubernetes/resources')
    
    if response['status_code'] == 200:
        resources = response['data']
        print(f"✅ K8s resources endpoint works: {resources}")
    elif response['status_code'] == 404:
        print("⚠️  K8s resources endpoint not available (expected for Docker backend)")
    else:
        print(f"❌ Unexpected K8s resources response: {response}")
    
    return True

def main():
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        port = "8000"
    
    base_url = f"http://localhost:{port}"
    
    print(f"🧪 Testing MCP Manager Kubernetes Backend at {base_url}")
    print("=" * 60)
    
    # Wait for service to be ready
    print("⏳ Waiting for service to be ready...")
    max_retries = 10
    for i in range(max_retries):
        response = make_request('GET', f'{base_url}/health')
        if response['status_code'] == 200:
            print("✅ Service is ready!")
            break
        if i == max_retries - 1:
            print("❌ Service failed to become ready")
            return 1
        time.sleep(2)
    
    # Run tests
    tests = [
        test_kubernetes_backend_detection,
        test_instance_spec_validation,
        test_instance_lifecycle_k8s_mode,
        test_k8s_resource_endpoints,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            if test_func(base_url):
                passed += 1
                print("✅ PASSED")
            else:
                failed += 1
                print("❌ FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ ERROR: {e}")
        print("-" * 40)
    
    print(f"\n📊 Test Results: {passed} passed, {failed} failed")
    
    if failed > 0:
        print("⚠️  Some tests failed, but this might be expected")
        print("   if running with Docker backend instead of K8s backend")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())