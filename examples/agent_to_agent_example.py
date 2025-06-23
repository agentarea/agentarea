#!/usr/bin/env python3
"""
Agent-to-Agent Communication Example for AgentArea

This script demonstrates how agents can communicate with each other using
the A2A protocol in AgentArea. It shows:
1. Setting up two agents (a primary agent and a helper agent)
2. Configuring them with A2A capabilities
3. Having the primary agent create a task for the helper agent
4. Getting results from the helper agent

Usage:
    python agent_to_agent_example.py

Requirements:
    - AgentArea platform running
    - Google ADK installed
    - Required environment variables set (see below)
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from typing import Dict, Any, Optional, Tuple

import requests
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.tools import Tool, ToolSpec
from google.genai import types

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = os.environ.get("AGENTAREA_API_URL", "http://localhost:8000/v1")
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Agent configurations
PRIMARY_AGENT_CONFIG = {
    "name": "Primary Agent",
    "description": "An agent that can delegate tasks to other agents",
    "instruction": """You are a primary agent that can delegate tasks to helper agents.
    When you need specialized knowledge or assistance, use the ask_agent tool to communicate with helper agents.
    Always explain your reasoning and why you're delegating a task.""",
    "model_id": "ollama_chat/qwen2.5",  # Adjust based on available models
}

HELPER_AGENT_CONFIG = {
    "name": "Helper Agent",
    "description": "A specialized agent that assists the primary agent",
    "instruction": """You are a helper agent with expertise in mathematics, data analysis, and research.
    When asked a question by another agent, provide detailed and accurate responses.
    Always show your work and explain your reasoning step by step.""",
    "model_id": "ollama_chat/qwen2.5",  # Adjust based on available models
}


async def create_agent(config: Dict[str, Any]) -> str:
    """
    Create an agent in AgentArea.
    
    Args:
        config: Agent configuration
        
    Returns:
        The ID of the created agent
    """
    url = f"{API_BASE_URL}/agents/"
    
    try:
        response = requests.post(url, headers=HEADERS, json=config)
        response.raise_for_status()
        agent_data = response.json()
        agent_id = agent_data.get("id")
        logger.info(f"Created agent: {config['name']} (ID: {agent_id})")
        return agent_id
    except requests.exceptions.RequestException as e:
        logger.error(f"Error creating agent: {e}")
        if hasattr(e, "response") and e.response:
            logger.error(f"Response: {e.response.text}")
        raise


async def create_task_for_agent(
    agent_id: str,
    message: str,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    Create a task for an agent using the A2A protocol.
    
    Args:
        agent_id: ID of the agent to create the task for
        message: Message to send to the agent
        user_id: Optional user ID
        metadata: Additional metadata for the task
        
    Returns:
        Tuple of (task_id, task_data)
    """
    url = f"{API_BASE_URL}/tasks/"
    
    # Generate a unique task ID
    task_id = str(uuid.uuid4())
    
    # Prepare metadata with agent ID
    task_metadata = metadata or {}
    task_metadata["agent_id"] = agent_id
    
    if user_id:
        task_metadata["user_id"] = user_id
    
    # Create payload
    payload = {
        "message": message,
        "agent_id": agent_id,
        "metadata": task_metadata
    }
    
    try:
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        task_data = response.json()
        logger.info(f"Created task for agent {agent_id}: {task_data['id']}")
        return task_data["id"], task_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error creating task: {e}")
        if hasattr(e, "response") and e.response:
            logger.error(f"Response: {e.response.text}")
        raise


async def get_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get the status of a task.
    
    Args:
        task_id: ID of the task to check
        
    Returns:
        Task status information
    """
    url = f"{API_BASE_URL}/tasks/{task_id}"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        task_data = response.json()
        return task_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting task status: {e}")
        if hasattr(e, "response") and e.response:
            logger.error(f"Response: {e.response.text}")
        raise


async def wait_for_task_completion(task_id: str, max_wait_time: int = 60, poll_interval: int = 2) -> Dict[str, Any]:
    """
    Wait for a task to complete and return the result.
    
    Args:
        task_id: ID of the task to wait for
        max_wait_time: Maximum time to wait in seconds
        poll_interval: How often to check task status in seconds
        
    Returns:
        Task result
        
    Raises:
        TimeoutError: If the task does not complete within the maximum wait time
    """
    elapsed_time = 0
    
    while elapsed_time < max_wait_time:
        task_data = await get_task_status(task_id)
        status = task_data.get("status", {}).get("state")
        
        if status in ["completed", "failed", "canceled"]:
            logger.info(f"Task {task_id} finished with status: {status}")
            return task_data
        
        logger.info(f"Task {task_id} status: {status}, waiting...")
        await asyncio.sleep(poll_interval)
        elapsed_time += poll_interval
    
    raise TimeoutError(f"Timed out waiting for task {task_id} to complete")


class AgentCommunicationTool(Tool):
    """Google ADK Tool for agent-to-agent communication."""
    
    def __init__(self, helper_agent_id: str):
        """Initialize the agent communication tool.
        
        Args:
            helper_agent_id: ID of the helper agent
        """
        self.helper_agent_id = helper_agent_id
        
        # Define tool specification
        spec = ToolSpec(
            name="ask_agent",
            description="Ask another agent to perform a task and get the result",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Message to send to the helper agent"
                    },
                    "wait_for_response": {
                        "type": "boolean",
                        "description": "Whether to wait for the response or just create the task",
                        "default": True
                    }
                },
                "required": ["message"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the created task"
                    },
                    "status": {
                        "type": "string",
                        "description": "Status of the task"
                    },
                    "response": {
                        "type": "string",
                        "description": "Response from the agent (if wait_for_response is True)"
                    }
                }
            }
        )
        
        super().__init__(spec=spec)
    
    async def execute(self, message: str, wait_for_response: bool = True) -> Dict[str, Any]:
        """Execute the tool by asking the helper agent to perform a task.
        
        Args:
            message: Message to send to the helper agent
            wait_for_response: Whether to wait for the response
            
        Returns:
            Dictionary with task_id, status, and optionally response
        """
        try:
            # Create task for the helper agent
            task_id, task = await create_task_for_agent(
                agent_id=self.helper_agent_id,
                message=message,
                metadata={"is_agent_to_agent": True}
            )
            
            result = {
                "task_id": task_id,
                "status": task.get("status", {}).get("state", "unknown")
            }
            
            # If wait_for_response is True, wait for the task to complete
            if wait_for_response:
                task_result = await wait_for_task_completion(task_id)
                
                # Extract response from the task result
                response = "Task completed but no response found"
                
                if "history" in task_result and task_result["history"]:
                    for message in reversed(task_result["history"]):
                        if message.get("role") == "agent":
                            for part in message.get("parts", []):
                                if part.get("type") == "text" and "text" in part:
                                    response = part["text"]
                                    break
                            if response != "Task completed but no response found":
                                break
                
                result["response"] = response
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing ask_agent tool: {e}", exc_info=True)
            return {
                "task_id": None,
                "status": "failed",
                "error": str(e)
            }


async def setup_agents() -> Tuple[str, str]:
    """
    Set up the primary and helper agents.
    
    Returns:
        Tuple of (primary_agent_id, helper_agent_id)
    """
    logger.info("Setting up agents...")
    
    # Create the helper agent
    helper_agent_id = await create_agent(HELPER_AGENT_CONFIG)
    
    # Create the primary agent
    primary_agent_id = await create_agent(PRIMARY_AGENT_CONFIG)
    
    return primary_agent_id, helper_agent_id


async def run_primary_agent_with_helper(primary_agent_id: str, helper_agent_id: str, query: str) -> Dict[str, Any]:
    """
    Run the primary agent with a query, allowing it to delegate to the helper agent.
    
    Args:
        primary_agent_id: ID of the primary agent
        helper_agent_id: ID of the helper agent
        query: Query for the primary agent
        
    Returns:
        Result of the primary agent's execution
    """
    logger.info(f"Running primary agent with query: {query}")
    
    # Create a task for the primary agent
    task_id, task = await create_task_for_agent(
        agent_id=primary_agent_id,
        message=query,
        metadata={
            "enable_agent_communication": True,
            "helper_agent_id": helper_agent_id
        }
    )
    
    # Wait for the task to complete
    logger.info(f"Waiting for primary agent task {task_id} to complete...")
    task_result = await wait_for_task_completion(task_id)
    
    return task_result


async def simulate_agent_communication_locally(helper_agent_id: str, query: str) -> None:
    """
    Simulate agent-to-agent communication locally using Google ADK.
    
    This function demonstrates how to use the AgentCommunicationTool with
    a local LlmAgent instance.
    
    Args:
        helper_agent_id: ID of the helper agent
        query: Query for the primary agent
    """
    logger.info("Simulating agent-to-agent communication locally...")
    
    # Create the agent communication tool
    agent_comm_tool = AgentCommunicationTool(helper_agent_id)
    
    # Create a LiteLLM model
    model = LiteLlm(model="ollama_chat/qwen2.5")  # Adjust based on available models
    
    # Create the primary agent with the communication tool
    primary_agent = LlmAgent(
        name="Local Primary Agent",
        model=model,
        instruction=PRIMARY_AGENT_CONFIG["instruction"],
        tools=[agent_comm_tool]
    )
    
    # Create a runner for the primary agent
    runner = Runner(
        app_name="agent_to_agent_example",
        agent=primary_agent
    )
    
    # Create content from query
    content = types.Content(role="user", parts=[types.Part(text=query)])
    
    # Run the agent
    logger.info("Running local primary agent...")
    response = runner.run(
        user_id="example_user",
        new_message=content
    )
    
    # Print the response
    logger.info("Agent response:")
    for message in response.messages:
        if message.role == "agent":
            for part in message.parts:
                if hasattr(part, "text"):
                    print(f"Agent: {part.text}")


async def main():
    """Run the agent-to-agent communication example."""
    try:
        # Set up the agents
        primary_agent_id, helper_agent_id = await setup_agents()
        
        print(f"Primary Agent ID: {primary_agent_id}")
        print(f"Helper Agent ID: {helper_agent_id}")
        
        # Example 1: Run the primary agent with a query that requires helper agent assistance
        query1 = """
        I need to solve a complex math problem: What is the sum of the first 100 prime numbers?
        This is a difficult calculation, so please use the helper agent to solve it.
        """
        
        print("\n=== Example 1: Primary Agent Delegating to Helper Agent ===")
        result1 = await run_primary_agent_with_helper(primary_agent_id, helper_agent_id, query1)
        print(f"Task ID: {result1['id']}")
        print(f"Status: {result1['status']['state']}")
        
        # Extract and print the response
        if "history" in result1 and result1["history"]:
            for message in reversed(result1["history"]):
                if message.get("role") == "agent":
                    for part in message.get("parts", []):
                        if part.get("type") == "text" and "text" in part:
                            print(f"\nPrimary Agent Response:\n{part['text']}")
                            break
                    break
        
        # Example 2: Simulate agent communication locally
        print("\n=== Example 2: Local Simulation of Agent-to-Agent Communication ===")
        query2 = """
        I need to analyze the following data: [10, 15, 20, 25, 30, 35, 40, 45, 50].
        Please calculate the mean, median, and standard deviation.
        If you need help with the calculations, ask the helper agent.
        """
        
        await simulate_agent_communication_locally(helper_agent_id, query2)
        
        print("\n=== Examples completed successfully ===")
        
    except Exception as e:
        logger.error(f"Error running example: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
