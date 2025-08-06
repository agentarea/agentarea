#!/usr/bin/env python3
"""
Basic MCP Service Test - Tests endpoints that work without container runtime
"""

import urllib.request
import urllib.error
import json
import sys


def test_health(base_url):
    """Test health endpoint"""
    try:
        request = urllib.request.Request(f"{base_url}/health")
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode('utf-8'))
                print(f"✅ Health check passed: {data.get('status', 'unknown')} (v{data.get('version', 'unknown')})")
                return True
            else:
                print(f"❌ Health check failed: HTTP {response.getcode()}")
                return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False


def test_service_running(base_url):
    """Test if service is accessible at all"""
    try:
        request = urllib.request.Request(f"{base_url}/health")
        with urllib.request.urlopen(request, timeout=5):
            print(f"✅ Service is running and accessible at {base_url}")
            return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(f"⚠️  Service running but requires authentication (HTTP 401)")
            return True
        else:
            print(f"❌ Service returned HTTP {e.code}")
            return False
    except Exception as e:
        print(f"❌ Cannot connect to service: {e}")
        return False


def main():
    base_url = "http://localhost:7999"
    
    print("Basic MCP Service Connectivity Test")
    print("=" * 40)
    print(f"Testing: {base_url}")
    print()
    
    # Test 1: Basic connectivity
    if not test_service_running(base_url):
        print("\n❌ Service is not running or not accessible")
        sys.exit(1)
    
    # Test 2: Health endpoint  
    if test_health(base_url):
        print("\n🎉 Basic tests passed!")
        sys.exit(0)
    else:
        print("\n⚠️  Service is running but health check failed")
        sys.exit(1)


if __name__ == '__main__':
    main()