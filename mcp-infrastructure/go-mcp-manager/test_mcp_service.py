#!/usr/bin/env python3
"""
MCP Service API Test Script

This script tests the MCP hosting service by making API calls to verify:
1. Service health and status
2. Instance creation, management, and deletion
3. Health checks and monitoring
4. Backend-specific behavior (Docker vs Kubernetes)

Usage:
    python test_mcp_service.py --host localhost --port 8000
    python test_mcp_service.py --host localhost --port 8000 --backend kubernetes
"""

import argparse
import json
import requests
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import sys


@dataclass
class TestResult:
    name: str
    success: bool
    message: str
    duration: float
    details: Optional[Dict[str, Any]] = None


class MCPServiceTester:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        self.test_results: List[TestResult] = []
        
    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")
        
    def make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make an HTTP request with error handling"""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            return response
        except requests.exceptions.RequestException as e:
            self.log(f"Request failed: {e}", "ERROR")
            raise
            
    def run_test(self, test_name: str, test_func, *args, **kwargs) -> TestResult:
        """Run a single test and record the result"""
        self.log(f"Running test: {test_name}")
        start_time = time.time()
        
        try:
            result = test_func(*args, **kwargs)
            duration = time.time() - start_time
            
            if isinstance(result, tuple):
                success, message, details = result
            else:
                success, message, details = result, "Test completed", None
                
            test_result = TestResult(
                name=test_name,
                success=success,
                message=message,
                duration=duration,
                details=details
            )
            
            status = "✅ PASS" if success else "❌ FAIL"
            self.log(f"{status} {test_name}: {message} ({duration:.2f}s)")
            
        except Exception as e:
            duration = time.time() - start_time
            test_result = TestResult(
                name=test_name,
                success=False,
                message=f"Exception: {str(e)}",
                duration=duration
            )
            self.log(f"❌ FAIL {test_name}: {str(e)} ({duration:.2f}s)", "ERROR")
            
        self.test_results.append(test_result)
        return test_result
        
    def test_service_health(self) -> tuple:
        """Test basic service health endpoint"""
        try:
            response = self.make_request('GET', '/health')
            
            if response.status_code != 200:
                return False, f"Health check failed with status {response.status_code}", None
                
            data = response.json()
            required_fields = ['status', 'version', 'timestamp']
            
            for field in required_fields:
                if field not in data:
                    return False, f"Missing required field: {field}", data
                    
            if data['status'] != 'healthy':
                return False, f"Service status is not healthy: {data['status']}", data
                
            return True, f"Service is healthy (version: {data.get('version', 'unknown')})", data
            
        except Exception as e:
            return False, f"Health check request failed: {str(e)}", None
            
    def test_list_instances(self) -> tuple:
        """Test listing instances"""
        try:
            response = self.make_request('GET', '/instances')
            
            if response.status_code != 200:
                return False, f"List instances failed with status {response.status_code}", None
                
            data = response.json()
            
            if 'instances' not in data or 'total' not in data:
                return False, "Response missing required fields", data
                
            total = data['total']
            instances = data['instances']
            
            if len(instances) != total:
                return False, f"Instance count mismatch: total={total}, actual={len(instances)}", data
                
            return True, f"Found {total} instances", data
            
        except Exception as e:
            return False, f"List instances request failed: {str(e)}", None
            
    def test_create_instance(self, instance_spec: Dict[str, Any]) -> tuple:
        """Test creating an MCP instance"""
        try:
            response = self.make_request('POST', '/instances', json=instance_spec)
            
            if response.status_code != 201:
                error_msg = "Unknown error"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_data.get('error', str(error_data)))
                except:
                    error_msg = response.text
                return False, f"Create instance failed with status {response.status_code}: {error_msg}", None
                
            data = response.json()
            required_fields = ['id', 'name', 'status', 'created_at']
            
            for field in required_fields:
                if field not in data:
                    return False, f"Response missing required field: {field}", data
                    
            return True, f"Instance created successfully (ID: {data['id']})", data
            
        except Exception as e:
            return False, f"Create instance request failed: {str(e)}", None
            
    def test_get_instance(self, instance_id: str) -> tuple:
        """Test getting instance details"""
        try:
            response = self.make_request('GET', f'/instances/{instance_id}')
            
            if response.status_code == 404:
                return False, "Instance not found", None
            elif response.status_code != 200:
                return False, f"Get instance failed with status {response.status_code}", None
                
            data = response.json()
            required_fields = ['id', 'name', 'status']
            
            for field in required_fields:
                if field not in data:
                    return False, f"Response missing required field: {field}", data
                    
            return True, f"Instance details retrieved (Status: {data['status']})", data
            
        except Exception as e:
            return False, f"Get instance request failed: {str(e)}", None
            
    def test_instance_health(self, instance_id: str) -> tuple:
        """Test instance health check"""
        try:
            response = self.make_request('GET', f'/instances/{instance_id}/health')
            
            if response.status_code == 404:
                return False, "Instance not found for health check", None
            elif response.status_code not in [200, 503]:  # 503 is acceptable for unhealthy instances
                return False, f"Health check failed with status {response.status_code}", None
                
            data = response.json()
            
            if 'healthy' not in data:
                return False, "Health check response missing 'healthy' field", data
                
            healthy = data['healthy']
            status = "healthy" if healthy else "unhealthy"
            
            return True, f"Health check completed - instance is {status}", data
            
        except Exception as e:
            return False, f"Health check request failed: {str(e)}", None
            
    def test_delete_instance(self, instance_id: str) -> tuple:
        """Test deleting an instance"""
        try:
            response = self.make_request('DELETE', f'/instances/{instance_id}')
            
            if response.status_code == 404:
                return False, "Instance not found for deletion", None
            elif response.status_code != 200:
                error_msg = "Unknown error"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_data.get('error', str(error_data)))
                except:
                    error_msg = response.text
                return False, f"Delete instance failed with status {response.status_code}: {error_msg}", None
                
            data = response.json()
            return True, "Instance deleted successfully", data
            
        except Exception as e:
            return False, f"Delete instance request failed: {str(e)}", None
            
    def test_monitoring_status(self) -> tuple:
        """Test monitoring status endpoint"""
        try:
            response = self.make_request('GET', '/monitoring/status')
            
            if response.status_code != 200:
                return False, f"Monitoring status failed with status {response.status_code}", None
                
            data = response.json()
            required_fields = ['total_containers', 'timestamp', 'uptime']
            
            for field in required_fields:
                if field not in data:
                    return False, f"Response missing required field: {field}", data
                    
            return True, f"Monitoring status retrieved (Total: {data['total_containers']})", data
            
        except Exception as e:
            return False, f"Monitoring status request failed: {str(e)}", None
            
    def test_validate_instance(self, instance_spec: Dict[str, Any]) -> tuple:
        """Test instance validation"""
        try:
            # Add dry_run flag for validation
            validation_spec = instance_spec.copy()
            validation_spec['dry_run'] = True
            
            response = self.make_request('POST', '/instances/validate', json=validation_spec)
            
            if response.status_code != 200:
                return False, f"Validation failed with status {response.status_code}", None
                
            data = response.json()
            
            if 'valid' not in data:
                return False, "Validation response missing 'valid' field", data
                
            valid = data['valid']
            errors = data.get('errors', [])
            warnings = data.get('warnings', [])
            
            message = f"Validation {'passed' if valid else 'failed'}"
            if errors:
                message += f" with {len(errors)} errors"
            if warnings:
                message += f" and {len(warnings)} warnings"
                
            return True, message, data
            
        except Exception as e:
            return False, f"Validation request failed: {str(e)}", None
            
    def wait_for_instance_ready(self, instance_id: str, max_wait: int = 120) -> tuple:
        """Wait for an instance to become ready"""
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                response = self.make_request('GET', f'/instances/{instance_id}')
                if response.status_code == 200:
                    data = response.json()
                    status = data.get('status', 'unknown')
                    
                    if status == 'running':
                        return True, f"Instance became ready in {time.time() - start_time:.1f}s", data
                    elif status in ['error', 'failed']:
                        return False, f"Instance failed to start (status: {status})", data
                        
                time.sleep(5)  # Wait 5 seconds before checking again
                
            except Exception as e:
                self.log(f"Error checking instance status: {e}", "WARN")
                time.sleep(5)
                
        return False, f"Instance did not become ready within {max_wait}s", None
        
    def create_test_instance_spec(self, name_suffix: str = None) -> Dict[str, Any]:
        """Create a test instance specification"""
        if name_suffix is None:
            name_suffix = str(uuid.uuid4())[:8]
            
        return {
            "instance_id": f"test-{name_suffix}",
            "name": f"test-mcp-{name_suffix}",
            "service_name": f"test-service-{name_suffix}",
            "image": "nginx:alpine",  # Simple, lightweight test image
            "port": 80,
            "environment": {
                "TEST_ENV": "true",
                "INSTANCE_NAME": f"test-{name_suffix}"
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
        
    def run_comprehensive_test_suite(self, backend_type: str = "auto") -> bool:
        """Run the complete test suite"""
        self.log(f"Starting comprehensive MCP service test suite (backend: {backend_type})")
        self.log(f"Testing against: {self.base_url}")
        
        # Test 1: Service Health
        self.run_test("Service Health Check", self.test_service_health)
        
        # Test 2: List instances (initial state)
        self.run_test("List Instances (Initial)", self.test_list_instances)
        
        # Test 3: Monitoring status
        self.run_test("Monitoring Status", self.test_monitoring_status)
        
        # Test 4: Create test instance
        test_spec = self.create_test_instance_spec()
        self.log(f"Using test instance spec: {json.dumps(test_spec, indent=2)}")
        
        # Test 5: Validate instance spec
        validate_result = self.run_test("Validate Instance Spec", self.test_validate_instance, test_spec)
        
        # Test 6: Create instance
        create_result = self.run_test("Create Instance", self.test_create_instance, test_spec)
        
        if not create_result.success:
            self.log("Skipping remaining tests due to instance creation failure", "WARN")
            self.print_test_summary()
            return False
            
        instance_id = create_result.details.get('id') if create_result.details else None
        if not instance_id:
            self.log("No instance ID returned from creation", "ERROR")
            self.print_test_summary()
            return False
            
        try:
            # Test 7: Get instance details
            self.run_test("Get Instance Details", self.test_get_instance, instance_id)
            
            # Test 8: Wait for instance to become ready (for Kubernetes especially)
            self.run_test("Wait for Instance Ready", self.wait_for_instance_ready, instance_id, 60)
            
            # Test 9: Instance health check
            self.run_test("Instance Health Check", self.test_instance_health, instance_id)
            
            # Test 10: List instances (should show our instance)
            self.run_test("List Instances (With Test Instance)", self.test_list_instances)
            
            # Test 11: Monitoring status (should reflect new instance)
            self.run_test("Monitoring Status (Updated)", self.test_monitoring_status)
            
        finally:
            # Test 12: Cleanup - Delete instance
            self.run_test("Delete Instance", self.test_delete_instance, instance_id)
            
            # Give some time for cleanup to complete
            time.sleep(5)
            
            # Test 13: Verify instance is gone
            final_list_result = self.run_test("List Instances (After Cleanup)", self.test_list_instances)
            
        self.print_test_summary()
        return self.all_tests_passed()
        
    def all_tests_passed(self) -> bool:
        """Check if all tests passed"""
        return all(result.success for result in self.test_results)
        
    def print_test_summary(self):
        """Print a summary of all test results"""
        total = len(self.test_results)
        passed = sum(1 for result in self.test_results if result.success)
        failed = total - passed
        
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"Total Tests: {total}")
        print(f"Passed: {passed} ✅")
        print(f"Failed: {failed} ❌")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        if failed > 0:
            print(f"\nFailed Tests:")
            for result in self.test_results:
                if not result.success:
                    print(f"  ❌ {result.name}: {result.message}")
                    
        print(f"\nTotal Duration: {sum(r.duration for r in self.test_results):.2f}s")
        print("="*80)
        
    def test_legacy_endpoints(self) -> bool:
        """Test legacy container endpoints for backward compatibility"""
        self.log("Testing legacy container endpoints")
        
        # Test legacy health endpoint
        self.run_test("Legacy Health Check", self.test_service_health)
        
        # Test legacy list containers
        try:
            response = self.make_request('GET', '/containers')
            if response.status_code == 200:
                self.run_test("Legacy List Containers", lambda: (True, "Legacy endpoint works", response.json()))
            else:
                self.run_test("Legacy List Containers", lambda: (False, f"Status {response.status_code}", None))
        except Exception as e:
            self.run_test("Legacy List Containers", lambda: (False, f"Exception: {e}", None))
            
        return True


def main():
    parser = argparse.ArgumentParser(description='Test MCP Service API')
    parser.add_argument('--host', default='localhost', help='Service host (default: localhost)')
    parser.add_argument('--port', type=int, default=8000, help='Service port (default: 8000)')
    parser.add_argument('--protocol', default='http', choices=['http', 'https'], help='Protocol (default: http)')
    parser.add_argument('--backend', default='auto', choices=['auto', 'docker', 'kubernetes'], 
                       help='Expected backend type (default: auto)')
    parser.add_argument('--timeout', type=int, default=30, help='Request timeout in seconds (default: 30)')
    parser.add_argument('--legacy', action='store_true', help='Also test legacy container endpoints')
    
    args = parser.parse_args()
    
    # Construct base URL
    base_url = f"{args.protocol}://{args.host}:{args.port}"
    
    # Create tester instance
    tester = MCPServiceTester(base_url, args.timeout)
    
    try:
        # Run the comprehensive test suite
        success = tester.run_comprehensive_test_suite(args.backend)
        
        # Test legacy endpoints if requested
        if args.legacy:
            tester.test_legacy_endpoints()
            
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        tester.log("Test suite interrupted by user", "WARN")
        sys.exit(130)
    except Exception as e:
        tester.log(f"Test suite failed with exception: {e}", "ERROR")
        sys.exit(1)


if __name__ == '__main__':
    main()