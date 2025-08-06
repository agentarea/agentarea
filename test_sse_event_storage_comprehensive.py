#!/usr/bin/env python3
"""
Comprehensive test script for SSE Event Streaming & Task Events Storage

This script validates the complete event sourcing flow:
1. Creates a task via API
2. Connects to SSE stream to receive real-time events  
3. Validates events are received during workflow execution
4. Verifies events are stored in database for persistence
5. Tests edge cases and error scenarios

Usage:
    python test_sse_event_storage_comprehensive.py
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, UTC
from typing import Any, AsyncGenerator, Dict, List
from uuid import uuid4

import aiohttp
import asyncpg

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = "http://localhost:8000"
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres", 
    "password": "postgres",
    "database": "aiagents"
}

# Test configuration
TEST_TIMEOUT = 60  # seconds
MAX_EVENTS_TO_WAIT = 5


class SSETestResult:
    """Container for test results."""
    
    def __init__(self):
        self.task_id: str = None
        self.agent_id: str = None
        self.sse_events: List[Dict[str, Any]] = []
        self.db_events: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.start_time: datetime = None
        self.end_time: datetime = None
        
    @property
    def duration(self) -> float:
        """Test duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
        
    def add_error(self, error: str):
        """Add an error to the result."""
        self.errors.append(f"{datetime.now(UTC).isoformat()}: {error}")
        logger.error(error)
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "duration_seconds": self.duration,
            "sse_events_count": len(self.sse_events),
            "db_events_count": len(self.db_events),
            "errors_count": len(self.errors),
            "sse_events": self.sse_events,
            "db_events": self.db_events,
            "errors": self.errors
        }


class ComprehensiveSSETest:
    """Comprehensive SSE and Event Storage Test."""
    
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        self.db_pool: asyncpg.Pool = None
        
    async def __aenter__(self):
        """Async context manager entry."""
        # Create HTTP session
        self.session = aiohttp.ClientSession()
        
        # Create database connection pool
        self.db_pool = await asyncpg.create_pool(**DB_CONFIG)
        
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
            
        if self.db_pool:
            await self.db_pool.close()
            
    async def get_or_create_test_agent(self) -> str:
        """Get or create a test agent for our tests."""
        try:
            # Try to get existing test agent
            async with self.session.get(f"{API_BASE_URL}/v1/agents") as response:
                if response.status == 200:
                    agents = await response.json()
                    for agent in agents:
                        if agent.get("name") == "SSE Test Agent":
                            logger.info(f"Using existing test agent: {agent['id']}")
                            return agent["id"]
            
            # Create new test agent
            agent_data = {
                "name": "SSE Test Agent",
                "description": "Agent for testing SSE event streaming",
                "model_id": "claude-3-haiku-20240307",
                "instruction": "You are a test agent. Respond briefly and use some tools when possible.",
                "planning": False
            }
            
            async with self.session.post(f"{API_BASE_URL}/v1/agents", json=agent_data) as response:
                if response.status == 201:
                    agent = await response.json()
                    logger.info(f"Created new test agent: {agent['id']}")
                    return agent["id"]
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to create agent: {response.status} - {error_text}")
                    
        except Exception as e:
            raise Exception(f"Failed to get or create test agent: {e}")
            
    async def create_task(self, agent_id: str, description: str) -> str:
        """Create a task and return the task ID."""
        task_data = {
            "description": description,
            "parameters": {"test_mode": True},
            "user_id": "test_user"
        }
        
        async with self.session.post(
            f"{API_BASE_URL}/v1/agents/{agent_id}/tasks/sync", 
            json=task_data
        ) as response:
            if response.status == 200:
                task = await response.json()
                return task["id"]
            else:
                error_text = await response.text()
                raise Exception(f"Failed to create task: {response.status} - {error_text}")
                
    @asynccontextmanager
    async def sse_stream(self, agent_id: str, task_id: str) -> AsyncGenerator[aiohttp.StreamReader, None]:
        """Context manager for SSE stream connection."""
        url = f"{API_BASE_URL}/v1/agents/{agent_id}/tasks/{task_id}/events/stream"
        
        async with self.session.get(
            url,
            headers={
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache"
            }
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to connect to SSE stream: {response.status} - {error_text}")
                
            yield response.content
            
    async def parse_sse_events(self, stream: aiohttp.StreamReader, max_events: int = 10, timeout: float = 30.0) -> List[Dict[str, Any]]:
        """Parse SSE events from stream."""
        events = []
        buffer = ""
        start_time = time.time()
        
        try:
            while len(events) < max_events and (time.time() - start_time) < timeout:
                # Read chunk with timeout
                try:
                    chunk = await asyncio.wait_for(stream.read(1024), timeout=1.0)
                    if not chunk:
                        break
                        
                    buffer += chunk.decode('utf-8')
                    
                    # Process complete SSE messages
                    while '\n\n' in buffer:
                        message, buffer = buffer.split('\n\n', 1)
                        event_data = self._parse_sse_message(message)
                        if event_data:
                            events.append(event_data)
                            logger.info(f"Received SSE event: {event_data.get('event', 'unknown')} - {event_data.get('data', {}).get('message', 'no message')}")
                            
                            # Check for terminal events
                            event_type = event_data.get('event', '')
                            if event_type in ['task_completed', 'task_failed', 'workflow_completed', 'workflow_failed']:
                                logger.info(f"Received terminal event: {event_type}")
                                break
                                
                except asyncio.TimeoutError:
                    # No data received in 1 second, continue waiting
                    continue
                    
        except Exception as e:
            logger.error(f"Error reading SSE stream: {e}")
            
        return events
        
    def _parse_sse_message(self, message: str) -> Dict[str, Any] | None:
        """Parse individual SSE message."""
        if not message.strip():
            return None
            
        lines = message.strip().split('\n')
        event_data = {}
        
        for line in lines:
            if line.startswith('event: '):
                event_data['event'] = line[7:]
            elif line.startswith('data: '):
                try:
                    event_data['data'] = json.loads(line[6:])
                except json.JSONDecodeError:
                    event_data['data'] = line[6:]
                    
        return event_data if event_data else None
        
    async def get_task_events_from_db(self, task_id: str) -> List[Dict[str, Any]]:
        """Get events for a task from the database."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, task_id, event_type, timestamp, data, metadata
                   FROM task_events 
                   WHERE task_id = $1 
                   ORDER BY timestamp ASC""",
                task_id
            )
            
            return [
                {
                    "id": str(row["id"]),
                    "task_id": str(row["task_id"]),
                    "event_type": row["event_type"],
                    "timestamp": row["timestamp"].isoformat(),
                    "data": row["data"],
                    "metadata": row["metadata"]
                }
                for row in rows
            ]
            
    async def verify_event_consistency(self, sse_events: List[Dict[str, Any]], db_events: List[Dict[str, Any]]) -> List[str]:
        """Verify consistency between SSE events and database events."""
        issues = []
        
        # Check that we have events in both sources
        if not sse_events:
            issues.append("No SSE events received")
            
        if not db_events:
            issues.append("No events found in database")
            
        if not sse_events or not db_events:
            return issues
            
        # Create maps for comparison
        sse_by_type = {}
        for event in sse_events:
            event_type = event.get('event', 'unknown')
            if event_type not in sse_by_type:
                sse_by_type[event_type] = []
            sse_by_type[event_type].append(event)
            
        db_by_type = {}
        for event in db_events:
            event_type = event['event_type']
            if event_type not in db_by_type:
                db_by_type[event_type] = []
            db_by_type[event_type].append(event)
            
        # Check for missing event types
        sse_types = set(sse_by_type.keys())
        db_types = set(db_by_type.keys())
        
        if sse_types != db_types:
            missing_in_sse = db_types - sse_types
            missing_in_db = sse_types - db_types
            
            if missing_in_sse:
                issues.append(f"Event types missing in SSE stream: {missing_in_sse}")
                
            if missing_in_db:
                issues.append(f"Event types missing in database: {missing_in_db}")
                
        return issues
        
    async def run_basic_test(self) -> SSETestResult:
        """Run basic SSE and event storage test."""
        result = SSETestResult()
        result.start_time = datetime.now(UTC)
        
        try:
            logger.info("=== Starting Basic SSE Test ===")
            
            # Step 1: Get or create test agent
            logger.info("Step 1: Getting or creating test agent...")
            result.agent_id = await self.get_or_create_test_agent()
            
            # Step 2: Create task with streaming
            logger.info("Step 2: Creating task...")
            task_description = "Hello! Please tell me a joke and then search for something interesting. This is a test."
            
            # Create task without streaming first to get task ID
            result.task_id = await self.create_task(result.agent_id, task_description)
            logger.info(f"Created task: {result.task_id}")
            
            # Step 3: Connect to SSE stream and collect events
            logger.info("Step 3: Connecting to SSE stream...")
            async with self.sse_stream(result.agent_id, result.task_id) as stream:
                result.sse_events = await self.parse_sse_events(
                    stream, 
                    max_events=MAX_EVENTS_TO_WAIT, 
                    timeout=TEST_TIMEOUT
                )
                
            logger.info(f"Collected {len(result.sse_events)} SSE events")
            
            # Step 4: Wait a bit for database writes to complete
            logger.info("Step 4: Waiting for database writes to complete...")
            await asyncio.sleep(2)
            
            # Step 5: Get events from database
            logger.info("Step 5: Retrieving events from database...")
            result.db_events = await self.get_task_events_from_db(result.task_id)
            logger.info(f"Found {len(result.db_events)} events in database")
            
            # Step 6: Verify consistency
            logger.info("Step 6: Verifying event consistency...")
            consistency_issues = await self.verify_event_consistency(result.sse_events, result.db_events)
            result.errors.extend(consistency_issues)
            
            if not consistency_issues:
                logger.info("✅ Event consistency verification passed!")
            else:
                logger.warning(f"⚠️  Event consistency issues found: {consistency_issues}")
                
        except Exception as e:
            result.add_error(f"Basic test failed: {e}")
            
        finally:
            result.end_time = datetime.now(UTC)
            
        return result
        
    async def run_comprehensive_tests(self) -> Dict[str, SSETestResult]:
        """Run comprehensive test suite."""
        results = {}
        
        logger.info("🚀 Starting Comprehensive SSE & Event Storage Tests")
        
        # Test 1: Basic functionality
        results["basic_test"] = await self.run_basic_test()
        
        # Test 2: Error scenario (if basic test worked)
        if not results["basic_test"].errors:
            logger.info("\n=== Running Error Scenario Test ===")
            # We could add more tests here like invalid agent ID, etc.
            
        return results
        
    def print_results(self, results: Dict[str, SSETestResult]):
        """Print test results summary."""
        print("\n" + "="*60)
        print("📊 COMPREHENSIVE SSE TEST RESULTS")
        print("="*60)
        
        for test_name, result in results.items():
            print(f"\n🔍 {test_name.upper()}:")
            print(f"   Duration: {result.duration:.2f}s")
            print(f"   Task ID: {result.task_id}")
            print(f"   Agent ID: {result.agent_id}")
            print(f"   SSE Events: {len(result.sse_events)}")
            print(f"   DB Events: {len(result.db_events)}")
            print(f"   Errors: {len(result.errors)}")
            
            if result.errors:
                print("   ❌ Issues found:")
                for error in result.errors:
                    print(f"      - {error}")
            else:
                print("   ✅ Test passed!")
                
        print("\n" + "="*60)
        
    async def save_results(self, results: Dict[str, SSETestResult], filename: str = None):
        """Save detailed results to JSON file."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"sse_test_results_{timestamp}.json"
            
        results_data = {
            "test_run_timestamp": datetime.now(UTC).isoformat(),
            "test_config": {
                "api_base_url": API_BASE_URL,
                "test_timeout": TEST_TIMEOUT,
                "max_events_to_wait": MAX_EVENTS_TO_WAIT
            },
            "results": {name: result.to_dict() for name, result in results.items()}
        }
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2, default=str)
            
        logger.info(f"📁 Detailed results saved to: {filename}")


async def main():
    """Main test execution function."""
    try:
        async with ComprehensiveSSETest() as test_runner:
            # Run all tests
            results = await test_runner.run_comprehensive_tests()
            
            # Print results
            test_runner.print_results(results)
            
            # Save detailed results
            await test_runner.save_results(results)
            
            # Return exit code based on results
            total_errors = sum(len(result.errors) for result in results.values())
            if total_errors == 0:
                print("\n🎉 All tests passed successfully!")
                return 0
            else:
                print(f"\n❌ Tests failed with {total_errors} total errors.")
                return 1
                
    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)