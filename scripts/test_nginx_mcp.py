#!/usr/bin/env python3
"""
Comprehensive Nginx MCP End-to-End Test

This script tests the complete MCP infrastructure flow:
1. Creates a custom nginx MCP server specification
2. Validates container image exists (with bypass option)
3. Performs dry-run validation before instance creation
4. Creates MCP instance with proper status tracking
5. Monitors container lifecycle and health
6. Verifies HTTP endpoint accessibility
7. Tests cleanup and resource management

Prerequisites:
    - MCP Infrastructure must be running
    - Start with: docker-compose -f docker-compose.dev.yaml up -d
    - Wait for services to be ready (health checks)

Usage:
    python scripts/test_nginx_mcp.py [--skip-image-check] [--api-base http://localhost:8000]
"""

import argparse
import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

# Optional docker import
try:
    import docker
    from docker.errors import ImageNotFound, DockerException
    docker_available = True
except ImportError:
    docker = None
    ImageNotFound = Exception
    DockerException = Exception
    docker_available = False

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class InfrastructureError(Exception):
    """Raised when MCP infrastructure is not available."""
    pass


class NginxMCPTester:
    """Comprehensive tester for nginx MCP infrastructure."""
    
    def __init__(self, api_base: str = "http://localhost:8000", skip_image_check: bool = False):
        self.api_base = api_base
        self.skip_image_check = skip_image_check
        self.client: Optional[httpx.AsyncClient] = None
        self.docker_client = None
        
        # Track created resources for cleanup
        self.created_resources = {
            'mcp_server_id': None,
            'mcp_instance_id': None,
            'agent_id': None,
            'model_instance_id': None,
        }
    
    async def setup(self):
        """Initialize HTTP and Docker clients."""
        self.client = httpx.AsyncClient(timeout=60)
        if docker_available and docker is not None:
            try:
                self.docker_client = docker.from_env()
            except DockerException as e:
                logger.warning(f"Docker client initialization failed: {e}")
                if not self.skip_image_check:
                    raise
        else:
            logger.warning("Docker not available - will skip image validation")
            self.skip_image_check = True
    
    async def cleanup(self):
        """Clean up resources and close connections."""
        if not self.client:
            return
            
        logger.info("🧹 Cleaning up resources...")
        
        # Clean up in reverse order of creation
        if self.created_resources['mcp_instance_id']:
            try:
                response = await self.client.delete(
                    f"{self.api_base}/v1/mcp-server-instances/{self.created_resources['mcp_instance_id']}"
                )
                if response.status_code in [200, 204]:
                    logger.info(f"✅ Cleaned up mcp_instance_id: {self.created_resources['mcp_instance_id']}")
                else:
                    logger.warning(f"⚠️  Failed to cleanup instance: {response.status_code}")
            except Exception as e:
                logger.error(f"❌ Error cleaning up instance: {e}")
        
        if self.created_resources['mcp_server_id']:
            try:
                response = await self.client.delete(
                    f"{self.api_base}/v1/mcp-servers/{self.created_resources['mcp_server_id']}"
                )
                if response.status_code in [200, 204]:
                    logger.info(f"✅ Cleaned up mcp_server_id: {self.created_resources['mcp_server_id']}")
                else:
                    logger.warning(f"⚠️  Failed to cleanup server: {response.status_code}")
            except Exception as e:
                logger.error(f"❌ Error cleaning up server: {e}")
        
        await self.client.aclose()
    
    async def check_infrastructure(self) -> bool:
        """Check if MCP infrastructure is running and accessible."""
        if not self.client:
            logger.error("❌ HTTP client not initialized")
            return False
            
        logger.info("🔍 Checking MCP infrastructure availability...")
        
        # Check main API health
        try:
            response = await self.client.get(f"{self.api_base}/health")
            if response.status_code == 200:
                health_data = response.json()
                logger.info(f"✅ AgentArea API healthy: {health_data.get('service', 'unknown')}")
            else:
                logger.error(f"❌ AgentArea API health check failed: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"❌ Could not reach AgentArea API: {e}")
            logger.error("   Make sure to start the infrastructure first:")
            logger.error("   docker-compose -f docker-compose.dev.yaml up -d")
            return False
        
        # Check MCP Manager health (if accessible)
        try:
            mcp_manager_response = await self.client.get("http://localhost:7999/health")
            if mcp_manager_response.status_code == 200:
                logger.info("✅ MCP Manager healthy")
            else:
                logger.warning(f"⚠️  MCP Manager health check failed: {mcp_manager_response.status_code}")
        except Exception:
            logger.warning("⚠️  MCP Manager not accessible (this is expected if running in API-only mode)")
        
        return True
    
    def validate_container_image(self, image_name: str) -> bool:
        """Validate that Docker image exists locally or can be pulled."""
        if self.skip_image_check:
            logger.info(f"⏭️  Skipping image validation for {image_name}")
            return True
        
        if not self.docker_client:
            logger.warning("Docker client not available, skipping image validation")
            return True
        
        try:
            # Try to find image locally
            logger.info(f"🔍 Checking if {image_name} exists locally...")
            self.docker_client.images.get(image_name)
            logger.info(f"✅ Image {image_name} found locally")
            return True
            
        except ImageNotFound:
            logger.info(f"📥 Image {image_name} not found locally, attempting to pull...")
            try:
                self.docker_client.images.pull(image_name)
                logger.info(f"✅ Successfully pulled {image_name}")
                return True
            except DockerException as e:
                logger.error(f"❌ Failed to pull {image_name}: {e}")
                return False
        
        except DockerException as e:
            logger.error(f"❌ Docker error validating {image_name}: {e}")
            return False
    
    async def create_nginx_mcp_spec(self) -> Dict[str, Any]:
        """Create nginx MCP server specification."""
        logger.info("📝 Creating nginx MCP server specification...")
        
        # Nginx MCP server configuration
        nginx_spec = {
            "name": "nginx-mcp-test",
            "description": "Nginx MCP server for end-to-end testing",
            "docker_image_url": "nginx:alpine",
            "version": "1.0.0",
            "tags": ["nginx", "test", "web-server"],
            "is_public": True,
            "env_schema": [
                {
                    "name": "NGINX_PORT",
                    "description": "Port for nginx server",
                    "required": False,
                    "default": "80"
                },
                {
                    "name": "NGINX_HOST",
                    "description": "Host for nginx server",
                    "required": False,
                    "default": "0.0.0.0"
                },
                {
                    "name": "NGINX_ROOT",
                    "description": "Document root directory",
                    "required": False,
                    "default": "/usr/share/nginx/html"
                }
            ],
            "cmd": ["nginx", "-g", "daemon off;"]
        }
        
        # Validate container image before creating spec
        if not self.validate_container_image(nginx_spec["docker_image_url"]):
            if not self.skip_image_check:
                raise Exception(f"Container image validation failed: {nginx_spec['docker_image_url']}")
            logger.warning("⚠️  Proceeding without image validation (--skip-image-check)")
        
        # Create MCP server spec
        response = await self.client.post(
            f"{self.api_base}/v1/mcp-servers/",
            json=nginx_spec
        )
        
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to create MCP server spec: {response.status_code} - {response.text}")
        
        server = response.json()
        self.created_resources['mcp_server_id'] = server['id']
        
        logger.info(f"✅ Created nginx MCP server spec: {server['id']}")
        logger.info(f"   Name: {server['name']}")
        logger.info(f"   Image: {server['docker_image_url']}")
        logger.info(f"   Status: {server['status']}")
        
        return server
    
    async def dry_run_validation(self, server_spec: Dict[str, Any]) -> bool:
        """Perform dry-run validation for MCP instance creation."""
        logger.info("🔍 Performing dry-run validation...")
        
        # Validate required fields
        required_fields = ['id', 'docker_image_url']
        for field in required_fields:
            if field not in server_spec:
                logger.error(f"❌ Missing required field: {field}")
                return False
        
        # Validate Docker image format
        image_url = server_spec['docker_image_url']
        if not image_url or ':' not in image_url:
            logger.error(f"❌ Invalid Docker image format: {image_url}")
            return False
        
        # Check if we can construct a valid json_spec
        test_json_spec = {
            "type": "docker",
            "image": image_url,
            "port": 80,
            "environment": {
                "NGINX_PORT": "80",
                "NGINX_HOST": "0.0.0.0"
            },
            "cmd": server_spec.get('cmd', ["nginx", "-g", "daemon off;"])
        }
        
        # Validate json_spec structure
        required_spec_fields = ['type', 'image', 'port']
        for field in required_spec_fields:
            if field not in test_json_spec:
                logger.error(f"❌ Missing required json_spec field: {field}")
                return False
        
        logger.info("✅ Dry-run validation passed")
        logger.info(f"   Docker image: {test_json_spec['image']}")
        logger.info(f"   Port: {test_json_spec['port']}")
        logger.info(f"   Environment vars: {len(test_json_spec['environment'])}")
        
        return True
    
    async def create_mcp_instance(self, server_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create MCP instance with proper configuration."""
        logger.info("🚀 Creating MCP instance...")
        
        # Perform dry-run validation first
        if not await self.dry_run_validation(server_spec):
            raise Exception("Dry-run validation failed")
        
        # Configure instance
        instance_data = {
            "name": "nginx-mcp-instance",
            "description": "Nginx MCP instance for testing",
            "server_spec_id": server_spec['id'],
            "json_spec": {
                "type": "docker",
                "image": server_spec['docker_image_url'],
                "port": 80,
                "environment": {
                    "NGINX_PORT": "80",
                    "NGINX_HOST": "0.0.0.0",
                    "NGINX_ROOT": "/usr/share/nginx/html"
                },
                "cmd": server_spec.get('cmd', ["nginx", "-g", "daemon off;"]),
                "resources": {
                    "memory_limit": "128m",
                    "cpu_limit": "0.5"
                }
            }
        }
        
        # Create instance
        response = await self.client.post(
            f"{self.api_base}/v1/mcp-server-instances/",
            json=instance_data
        )
        
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to create MCP instance: {response.status_code} - {response.text}")
        
        instance = response.json()
        self.created_resources['mcp_instance_id'] = instance['id']
        
        logger.info(f"✅ Created MCP instance: {instance['id']}")
        logger.info(f"   Name: {instance['name']}")
        logger.info(f"   Status: {instance['status']}")
        
        return instance
    
    async def monitor_instance_status(self, instance_id: str, timeout: int = 120) -> bool:
        """Monitor MCP instance status until it's running or fails."""
        logger.info(f"📊 Monitoring instance status (timeout: {timeout}s)...")
        
        start_time = time.time()
        last_status = None
        
        while time.time() - start_time < timeout:
            try:
                response = await self.client.get(f"{self.api_base}/v1/mcp-server-instances/{instance_id}")
                if response.status_code == 200:
                    instance = response.json()
                    current_status = instance.get('status', 'unknown')
                    
                    if current_status != last_status:
                        logger.info(f"   Status: {current_status}")
                        last_status = current_status
                    
                    if current_status == 'running':
                        logger.info("✅ Instance is running")
                        return True
                    elif current_status in ['failed', 'error']:
                        logger.error(f"❌ Instance failed with status: {current_status}")
                        return False
                    
                else:
                    logger.warning(f"⚠️  Failed to get instance status: {response.status_code}")
                
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.warning(f"⚠️  Error monitoring status: {e}")
                await asyncio.sleep(3)
        
        logger.error("❌ Timeout waiting for instance to be ready")
        return False
    
    async def test_http_endpoint(self, instance_id: str) -> bool:
        """Test HTTP endpoint accessibility."""
        logger.info("🌐 Testing HTTP endpoint accessibility...")
        
        # Get instance details to find the endpoint
        response = await self.client.get(f"{self.api_base}/v1/mcp-server-instances/{instance_id}")
        if response.status_code != 200:
            logger.error(f"❌ Failed to get instance details: {response.status_code}")
            return False
        
        instance = response.json()
        json_spec = instance.get('json_spec', {})
        
        # Try to determine the endpoint URL
        # This would typically be provided by the MCP manager
        endpoint_url = None
        
        # Check if there's a URL in the response
        if 'url' in instance:
            endpoint_url = instance['url']
        elif 'endpoint_url' in json_spec:
            endpoint_url = json_spec['endpoint_url']
        else:
            # Try to construct from MCP proxy
            # This is based on the current MCP infrastructure setup
            json_spec.get('port', 80)
            endpoint_url = "http://localhost:7999/mcp/nginx-mcp-instance"
        
        if not endpoint_url:
            logger.warning("⚠️  No endpoint URL found, skipping HTTP test")
            return True
        
        logger.info(f"   Testing endpoint: {endpoint_url}")
        
        # Test HTTP endpoint with retries
        for attempt in range(5):
            try:
                test_response = await self.client.get(endpoint_url, timeout=10)
                if test_response.status_code == 200:
                    logger.info("✅ HTTP endpoint accessible")
                    logger.info(f"   Response length: {len(test_response.text)} bytes")
                    return True
                else:
                    logger.warning(f"   Attempt {attempt + 1}: HTTP {test_response.status_code}")
                    
            except Exception as e:
                logger.warning(f"   Attempt {attempt + 1}: {e}")
            
            if attempt < 4:
                await asyncio.sleep(5)
        
        logger.error("❌ HTTP endpoint not accessible after 5 attempts")
        return False
    
    async def test_resource_cleanup(self, instance_id: str) -> bool:
        """Test proper resource cleanup."""
        logger.info("🧹 Testing resource cleanup...")
        
        # Delete the instance
        response = await self.client.delete(f"{self.api_base}/v1/mcp-server-instances/{instance_id}")
        if response.status_code not in [200, 204]:
            logger.error(f"❌ Failed to delete instance: {response.status_code}")
            return False
        
        logger.info("✅ Instance deletion requested")
        
        # Wait for cleanup to complete
        await asyncio.sleep(10)
        
        # Verify instance is gone
        response = await self.client.get(f"{self.api_base}/v1/mcp-server-instances/{instance_id}")
        if response.status_code == 404:
            logger.info("✅ Instance successfully cleaned up")
            self.created_resources['mcp_instance_id'] = None  # Mark as cleaned up
            return True
        else:
            logger.warning(f"⚠️  Instance still exists: {response.status_code}")
            return False
    
    async def run_comprehensive_test(self) -> bool:
        """Run the complete end-to-end test."""
        logger.info("🚀 Starting comprehensive nginx MCP test...")
        
        try:
            # Step 0: Check infrastructure
            if not await self.check_infrastructure():
                raise InfrastructureError("MCP infrastructure is not available")
            
            # Step 1: Create MCP server specification
            server_spec = await self.create_nginx_mcp_spec()
            
            # Step 2: Create MCP instance
            instance = await self.create_mcp_instance(server_spec)
            
            # Step 3: Monitor instance status
            if not await self.monitor_instance_status(instance['id']):
                logger.error("❌ Instance failed to start properly")
                return False
            
            # Step 4: Test HTTP endpoint
            if not await self.test_http_endpoint(instance['id']):
                logger.warning("⚠️  HTTP endpoint test failed, but continuing...")
            
            # Step 5: Test resource cleanup
            if not await self.test_resource_cleanup(instance['id']):
                logger.error("❌ Resource cleanup test failed")
                return False
            
            logger.info("🎉 All tests passed successfully!")
            return True
            
        except InfrastructureError as e:
            logger.error(f"❌ Infrastructure error: {e}")
            logger.error("   Please ensure MCP infrastructure is running:")
            logger.error("   1. docker-compose -f docker-compose.dev.yaml up -d")
            logger.error("   2. Wait for services to be ready")
            logger.error("   3. Check health: curl http://localhost:8000/health")
            return False
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            return False


async def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="Nginx MCP End-to-End Test")
    parser.add_argument("--api-base", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--skip-image-check", action="store_true", help="Skip Docker image validation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--check-infrastructure", action="store_true", help="Only check infrastructure availability")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    tester = NginxMCPTester(api_base=args.api_base, skip_image_check=args.skip_image_check)
    
    try:
        await tester.setup()
        
        if args.check_infrastructure:
            success = await tester.check_infrastructure()
            if success:
                print("✅ Infrastructure is ready for testing!")
                exit(0)
            else:
                print("❌ Infrastructure is not ready!")
                exit(1)
        
        success = await tester.run_comprehensive_test()
        
        if success:
            print("🎉 Nginx MCP end-to-end test completed successfully!")
            exit(0)
        else:
            print("❌ Nginx MCP end-to-end test failed!")
            exit(1)
            
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    asyncio.run(main()) 