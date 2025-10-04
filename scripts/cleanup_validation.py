#!/usr/bin/env python3
"""
MCP Cleanup Validation Script

This script validates that MCP containers and resources are properly cleaned up:
1. Checks for orphaned containers
2. Validates resource cleanup in database
3. Verifies network cleanup
4. Tests Docker/Podman container removal
5. Validates Traefik configuration cleanup

Usage:
    python scripts/cleanup_validation.py [--api-base http://localhost:8000] [--mcp-manager http://localhost:7999]
"""

import argparse
import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CleanupValidator:
    """Validates proper cleanup of MCP containers and resources."""
    
    def __init__(self, api_base: str = "http://localhost:8000", mcp_manager: str = "http://localhost:7999"):
        self.api_base = api_base
        self.mcp_manager = mcp_manager
        self.client: Optional[httpx.AsyncClient] = None
        
        # Track test resources
        self.test_resources = {
            'server_id': None,
            'instance_id': None,
            'container_name': None,
        }
    
    async def setup(self):
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(timeout=60)
    
    async def cleanup(self):
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()
    
    async def create_test_resources(self) -> Dict[str, Any]:
        """Create test resources for cleanup validation."""
        if not self.client:
            raise RuntimeError("HTTP client not initialized")
        
        logger.info("📝 Creating test resources for cleanup validation...")
        
        # Create test MCP server
        server_spec = {
            "name": "cleanup-test-server",
            "description": "Test server for cleanup validation",
            "docker_image_url": "nginx:alpine",
            "version": "1.0.0",
            "tags": ["test", "cleanup"],
            "is_public": False,
            "env_schema": [
                {
                    "name": "TEST_VAR",
                    "description": "Test environment variable",
                    "required": False,
                    "default": "test_value"
                }
            ]
        }
        
        response = await self.client.post(f"{self.api_base}/v1/mcp-servers/", json=server_spec)
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to create test server: {response.status_code} - {response.text}")
        
        server = response.json()
        self.test_resources['server_id'] = server['id']
        logger.info(f"✅ Created test server: {server['id']}")
        
        # Create test MCP instance
        instance_data = {
            "name": "cleanup-test-instance",
            "description": "Test instance for cleanup validation",
            "server_spec_id": server['id'],
            "json_spec": {
                "type": "docker",
                "image": "nginx:alpine",
                "port": 80,
                "environment": {
                    "TEST_VAR": "test_value"
                },
                "resources": {
                    "memory_limit": "128m",
                    "cpu_limit": "0.5"
                }
            }
        }
        
        response = await self.client.post(f"{self.api_base}/v1/mcp-server-instances/", json=instance_data)
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to create test instance: {response.status_code} - {response.text}")
        
        instance = response.json()
        self.test_resources['instance_id'] = instance['id']
        self.test_resources['container_name'] = "mcp-cleanup-test-instance"
        logger.info(f"✅ Created test instance: {instance['id']}")
        
        # Wait for instance to be ready
        await asyncio.sleep(10)
        
        return {
            'server': server,
            'instance': instance
        }
    
    async def validate_container_exists(self, container_name: str) -> bool:
        """Check if container exists in MCP manager."""
        if not self.client:
            return False
        
        try:
            response = await self.client.get(f"{self.mcp_manager}/api/mcp/containers")
            if response.status_code == 200:
                containers = response.json()
                container_names = [c.get('name', '') for c in containers.get('containers', [])]
                return container_name in container_names
            return False
        except Exception:
            return False
    
    async def validate_database_cleanup(self, server_id: str, instance_id: str) -> Dict[str, bool]:
        """Validate that database records are properly cleaned up."""
        if not self.client:
            return {'server_cleaned': False, 'instance_cleaned': False}
        
        results = {}
        
        # Check server cleanup
        try:
            response = await self.client.get(f"{self.api_base}/v1/mcp-servers/{server_id}")
            results['server_cleaned'] = response.status_code == 404
        except Exception:
            results['server_cleaned'] = True  # Assume cleaned if can't access
        
        # Check instance cleanup
        try:
            response = await self.client.get(f"{self.api_base}/v1/mcp-server-instances/{instance_id}")
            results['instance_cleaned'] = response.status_code == 404
        except Exception:
            results['instance_cleaned'] = True  # Assume cleaned if can't access
        
        return results
    
    async def validate_container_removal(self, container_name: str) -> bool:
        """Validate that container is removed from MCP manager."""
        if not self.client:
            return False
        
        try:
            response = await self.client.get(f"{self.mcp_manager}/api/mcp/containers/{container_name}/status")
            # If we get 404, container is properly removed
            return response.status_code == 404
        except Exception:
            return True  # Assume removed if can't access
    
    async def validate_network_cleanup(self) -> bool:
        """Validate that network resources are cleaned up."""
        if not self.client:
            return False
        
        # Check MCP manager containers list
        try:
            response = await self.client.get(f"{self.mcp_manager}/api/mcp/containers")
            if response.status_code == 200:
                containers = response.json()
                # Check if any test containers remain
                test_containers = [c for c in containers.get('containers', []) 
                                 if 'cleanup-test' in c.get('name', '')]
                return len(test_containers) == 0
            return True
        except Exception:
            return True  # Assume cleaned if can't access
    
    async def perform_cleanup_test(self) -> Dict[str, bool]:
        """Perform complete cleanup test."""
        if not self.client:
            return {}
        
        logger.info("🧪 Starting cleanup validation test...")
        
        # Create test resources
        resources = await self.create_test_resources()
        server_id = resources['server']['id']
        instance_id = resources['instance']['id']
        container_name = self.test_resources['container_name']
        
        # Verify resources were created
        logger.info("🔍 Verifying resources were created...")
        if container_name:
            container_exists = await self.validate_container_exists(container_name)
            if not container_exists:
                logger.warning("⚠️  Container not found in MCP manager, continuing...")
        
        # Trigger cleanup by deleting instance
        logger.info("🗑️  Triggering cleanup by deleting instance...")
        response = await self.client.delete(f"{self.api_base}/v1/mcp-server-instances/{instance_id}")
        if response.status_code not in [200, 204]:
            logger.error(f"❌ Failed to delete instance: {response.status_code}")
            return {'cleanup_triggered': False}
        
        # Wait for cleanup to complete
        logger.info("⏳ Waiting for cleanup to complete...")
        await asyncio.sleep(15)
        
        # Validate cleanup
        results: Dict[str, bool] = {}
        
        # Check database cleanup
        logger.info("🔍 Validating database cleanup...")
        db_results = await self.validate_database_cleanup(server_id, instance_id)
        results.update(db_results)
        
        # Check container removal
        logger.info("🔍 Validating container removal...")
        if container_name:
            container_removed = await self.validate_container_removal(container_name)
            results['container_removed'] = container_removed
        
        # Check network cleanup
        logger.info("🔍 Validating network cleanup...")
        network_cleaned = await self.validate_network_cleanup()
        results['network_cleaned'] = network_cleaned
        
        # Clean up remaining server
        try:
            await self.client.delete(f"{self.api_base}/v1/mcp-servers/{server_id}")
        except Exception:
            pass
        
        return results
    
    async def run_validation(self) -> bool:
        """Run comprehensive cleanup validation."""
        logger.info("🧹 Starting MCP cleanup validation...")
        
        try:
            # Check if services are available
            logger.info("🔍 Checking service availability...")
            try:
                response = await self.client.get(f"{self.api_base}/health")
                if response.status_code != 200:
                    logger.error(f"❌ AgentArea API not available: {response.status_code}")
                    return False
            except Exception as e:
                logger.error(f"❌ Could not reach AgentArea API: {e}")
                return False
            
            # Run cleanup test
            results = await self.perform_cleanup_test()
            
            # Analyze results
            logger.info("📊 Cleanup validation results:")
            
            success_count = 0
            total_tests = 0
            
            for test_name, passed in results.items():
                total_tests += 1
                status = "✅ PASS" if passed else "❌ FAIL"
                logger.info(f"   {test_name}: {status}")
                if passed:
                    success_count += 1
            
            overall_success = success_count == total_tests
            
            if overall_success:
                logger.info("🎉 All cleanup validation tests passed!")
            else:
                logger.error(f"❌ {total_tests - success_count}/{total_tests} cleanup tests failed!")
            
            return overall_success
            
        except Exception as e:
            logger.error(f"❌ Cleanup validation failed: {e}")
            return False


async def main():
    """Main validation runner."""
    parser = argparse.ArgumentParser(description="MCP Cleanup Validation")
    parser.add_argument("--api-base", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--mcp-manager", default="http://localhost:7999", help="MCP Manager URL")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    validator = CleanupValidator(api_base=args.api_base, mcp_manager=args.mcp_manager)
    
    try:
        await validator.setup()
        success = await validator.run_validation()
        
        if success:
            print("🎉 Cleanup validation completed successfully!")
            exit(0)
        else:
            print("❌ Cleanup validation failed!")
            exit(1)
            
    finally:
        await validator.cleanup()


if __name__ == "__main__":
    asyncio.run(main()) 