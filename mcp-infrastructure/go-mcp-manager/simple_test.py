#!/usr/bin/env python3
"""
Simple MCP Service Test Script

A lightweight test script for the MCP hosting service that only uses standard library.
Tests basic functionality without external dependencies.

Usage:
    python simple_test.py
    python simple_test.py --host localhost --port 8000
"""

import argparse
import json
import urllib.request
import urllib.parse
import urllib.error
import time
import uuid
import sys


class SimpleMCPTester:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.test_count = 0
        self.passed_count = 0
        
    def log(self, message: str):
        """Log a message with timestamp"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
        
    def make_request(self, method: str, endpoint: str, data=None) -> dict:
        """Make an HTTP request using urllib"""
        url = f"{self.base_url}{endpoint}"
        
        # Prepare request
        req_data = None
        headers = {'Content-Type': 'application/json'}
        
        if data is not None:
            req_data = json.dumps(data).encode('utf-8')
            
        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_data = response.read().decode('utf-8')
                return {
                    'status_code': response.getcode(),
                    'data': json.loads(response_data) if response_data else {}
                }
        except urllib.error.HTTPError as e:
            error_data = {}
            try:
                error_body = e.read().decode('utf-8')
                error_data = json.loads(error_body) if error_body else {}
            except:
                pass
            return {
                'status_code': e.code,
                'data': error_data,
                'error': str(e)
            }
        except Exception as e:
            return {
                'status_code': 0,
                'error': str(e)
            }
            
    def test_assert(self, condition: bool, test_name: str, message: str = ""):
        """Assert a test condition and track results"""
        self.test_count += 1
        
        if condition:
            self.passed_count += 1
            status = "✅ PASS"
        else:
            status = "❌ FAIL"
            
        full_message = f"{status} {test_name}"
        if message:
            full_message += f": {message}"
            
        self.log(full_message)
        return condition
        
    def test_service_health(self):
        """Test the health endpoint"""
        self.log("Testing service health...")
        
        response = self.make_request('GET', '/health')
        
        success = self.test_assert(
            response['status_code'] == 200,
            "Health endpoint accessibility"
        )
        
        if success:
            data = response['data']
            self.test_assert(
                data.get('status') == 'healthy',
                "Service health status",
                f"Status: {data.get('status', 'unknown')}"
            )
            
            self.test_assert(
                'version' in data,
                "Version field present",
                f"Version: {data.get('version', 'missing')}"
            )
            
        return success
        
    def test_list_instances(self):
        """Test listing instances"""
        self.log("Testing instance listing...")
        
        response = self.make_request('GET', '/instances')
        
        success = self.test_assert(
            response['status_code'] == 200,
            "List instances endpoint"
        )
        
        if success:
            data = response['data']
            self.test_assert(
                'instances' in data and 'total' in data,
                "Response structure",
                f"Total: {data.get('total', 'missing')}"
            )
            
            instances = data.get('instances', [])
            total = data.get('total', 0)
            
            self.test_assert(
                len(instances) == total,
                "Instance count consistency",
                f"Listed: {len(instances)}, Total: {total}"
            )
            
        return success
        
    def test_monitoring_status(self):
        """Test monitoring status endpoint"""
        self.log("Testing monitoring status...")
        
        response = self.make_request('GET', '/monitoring/status')
        
        success = self.test_assert(
            response['status_code'] == 200,
            "Monitoring status endpoint"
        )
        
        if success:
            data = response['data']
            required_fields = ['total_containers', 'timestamp', 'uptime']
            
            for field in required_fields:
                self.test_assert(
                    field in data,
                    f"Monitoring field '{field}' present",
                    f"Value: {data.get(field, 'missing')}"
                )
                
        return success
        
    def test_instance_validation(self):
        """Test instance validation"""
        self.log("Testing instance validation...")
        
        # Create a test instance spec
        test_spec = {
            "instance_id": f"test-{uuid.uuid4().hex[:8]}",
            "name": f"test-validation",
            "service_name": f"test-validation-service",
            "image": "nginx:alpine",
            "port": 80,
            "workspace_id": "test-workspace",
            "dry_run": True
        }
        
        response = self.make_request('POST', '/instances/validate', test_spec)
        
        success = self.test_assert(
            response['status_code'] == 200,
            "Instance validation endpoint"
        )
        
        if success:
            data = response['data']
            self.test_assert(
                'valid' in data,
                "Validation result field present",
                f"Valid: {data.get('valid', 'missing')}"
            )
            
            # Check for validation fields
            for field in ['errors', 'warnings']:
                if field in data:
                    field_data = data[field]
                    self.log(f"  {field.title()}: {len(field_data) if isinstance(field_data, list) else 'not a list'}")
                    
        return success
        
    def test_instance_lifecycle(self):
        """Test creating, checking, and deleting an instance"""
        self.log("Testing instance lifecycle...")
        
        # Create test instance spec
        instance_id = f"test-{uuid.uuid4().hex[:8]}"
        test_spec = {
            "instance_id": instance_id,
            "name": f"test-lifecycle-{instance_id}",
            "service_name": f"test-service-{instance_id}",
            "image": "nginx:alpine",
            "port": 80,
            "environment": {
                "TEST_MODE": "true"
            },
            "workspace_id": "test-workspace",
            "resources": {
                "requests": {
                    "cpu": "100m",
                    "memory": "128Mi"
                },
                "limits": {
                    "cpu": "200m", 
                    "memory": "256Mi"
                }
            }
        }
        
        # Test instance creation
        self.log(f"Creating test instance: {instance_id}")
        response = self.make_request('POST', '/instances', test_spec)
        
        create_success = self.test_assert(
            response['status_code'] == 201,
            "Instance creation",
            f"Instance ID: {instance_id}"
        )
        
        if not create_success:
            error_msg = response.get('data', {}).get('message', response.get('error', 'Unknown error'))
            self.log(f"Creation failed: {error_msg}")
            return False
            
        created_instance = response['data']
        actual_instance_id = created_instance.get('id', instance_id)
        
        try:
            # Test getting instance details
            self.log(f"Getting instance details: {actual_instance_id}")
            response = self.make_request('GET', f'/instances/{actual_instance_id}')
            
            self.test_assert(
                response['status_code'] == 200,
                "Get instance details"
            )
            
            # Wait a bit and test health check
            self.log("Waiting 5 seconds before health check...")
            time.sleep(5)
            
            response = self.make_request('GET', f'/instances/{actual_instance_id}/health')
            
            # Health check can return 200 (healthy) or 503 (unhealthy) - both are valid
            health_success = self.test_assert(
                response['status_code'] in [200, 503],
                "Instance health check",
                f"Status: {response['status_code']}"
            )
            
            if health_success and response['status_code'] == 200:
                health_data = response['data']
                if 'healthy' in health_data:
                    is_healthy = health_data['healthy']
                    self.log(f"  Instance health: {'healthy' if is_healthy else 'unhealthy'}")
                    
        finally:
            # Always try to clean up the instance
            self.log(f"Cleaning up instance: {actual_instance_id}")
            response = self.make_request('DELETE', f'/instances/{actual_instance_id}')
            
            cleanup_success = self.test_assert(
                response['status_code'] in [200, 404],  # 404 is ok if already deleted
                "Instance cleanup"
            )
            
            if not cleanup_success:
                self.log(f"Warning: Failed to clean up instance {actual_instance_id}")
                
        return create_success
        
    def test_legacy_endpoints(self):
        """Test legacy container endpoints for backward compatibility"""
        self.log("Testing legacy endpoints...")
        
        # Test legacy containers endpoint
        response = self.make_request('GET', '/containers')
        
        # This may return 200 (Docker backend) or 404 (Kubernetes backend)
        legacy_available = response['status_code'] == 200
        
        self.test_assert(
            response['status_code'] in [200, 404],
            "Legacy containers endpoint",
            "Available" if legacy_available else "Not available (expected for K8s)"
        )
        
        return True
        
    def run_all_tests(self):
        """Run all tests"""
        self.log(f"Starting MCP Service tests against {self.base_url}")
        self.log("="*60)
        
        start_time = time.time()
        
        # Run individual test suites
        tests = [
            ("Service Health", self.test_service_health),
            ("List Instances", self.test_list_instances),
            ("Monitoring Status", self.test_monitoring_status),
            ("Instance Validation", self.test_instance_validation),
            ("Instance Lifecycle", self.test_instance_lifecycle),
            ("Legacy Endpoints", self.test_legacy_endpoints),
        ]
        
        for test_name, test_func in tests:
            self.log(f"\n--- {test_name} ---")
            try:
                test_func()
            except Exception as e:
                self.test_assert(False, f"{test_name} (Exception)", str(e))
                
        # Print summary
        duration = time.time() - start_time
        self.print_summary(duration)
        
        return self.passed_count == self.test_count
        
    def print_summary(self, duration: float):
        """Print test summary"""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Total Tests: {self.test_count}")
        print(f"Passed: {self.passed_count} ✅")
        print(f"Failed: {self.test_count - self.passed_count} ❌")
        
        if self.test_count > 0:
            success_rate = (self.passed_count / self.test_count) * 100
            print(f"Success Rate: {success_rate:.1f}%")
        else:
            print("Success Rate: N/A")
            
        print(f"Duration: {duration:.2f}s")
        print("="*60)
        
        if self.passed_count == self.test_count:
            print("🎉 All tests passed!")
        else:
            print("⚠️  Some tests failed. Check logs above for details.")


def main():
    parser = argparse.ArgumentParser(description='Simple MCP Service Test')
    parser.add_argument('--host', default='localhost', help='Service host')
    parser.add_argument('--port', type=int, default=8000, help='Service port')
    parser.add_argument('--protocol', default='http', choices=['http', 'https'], help='Protocol')
    parser.add_argument('--timeout', type=int, default=30, help='Request timeout')
    
    args = parser.parse_args()
    
    base_url = f"{args.protocol}://{args.host}:{args.port}"
    
    tester = SimpleMCPTester(base_url, args.timeout)
    
    try:
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()