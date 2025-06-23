#!/usr/bin/env python3
"""
Task Assignment Examples for AgentArea

This script demonstrates how to use the AgentArea API to:
1. Send tasks with user and agent IDs
2. Retrieve tasks by user ID
3. Retrieve tasks by agent ID

Usage:
    python task_assignment_examples.py

Requirements:
    - requests library (pip install requests)
"""

import json
import time
import uuid
from typing import Dict, Any, Optional

import requests

# Configuration
API_BASE_URL = "http://localhost:8000/v1"  # Adjust to your AgentArea API endpoint
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def generate_id() -> str:
    """Generate a unique ID for tasks, users, or agents."""
    return str(uuid.uuid4())


def create_task(
    message: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a new task with optional user and agent assignments.
    
    Args:
        message: The task message content
        user_id: Optional ID of the user creating the task
        agent_id: Optional ID of the agent to assign the task to
        metadata: Optional additional metadata for the task
        
    Returns:
        The created task data
    """
    url = f"{API_BASE_URL}/tasks/"
    
    payload = {
        "message": message,
    }
    
    if user_id:
        payload["user_id"] = user_id
    
    if agent_id:
        payload["agent_id"] = agent_id
    
    if metadata:
        payload["metadata"] = metadata
    
    try:
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error creating task: {e}")
        if hasattr(e, "response") and e.response:
            print(f"Response: {e.response.text}")
        raise


def get_tasks_by_user(user_id: str) -> Dict[str, Any]:
    """
    Retrieve all tasks associated with a specific user.
    
    Args:
        user_id: The ID of the user
        
    Returns:
        List of tasks and count
    """
    url = f"{API_BASE_URL}/tasks/user/{user_id}"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving tasks for user {user_id}: {e}")
        if hasattr(e, "response") and e.response:
            print(f"Response: {e.response.text}")
        raise


def get_tasks_by_agent(agent_id: str) -> Dict[str, Any]:
    """
    Retrieve all tasks assigned to a specific agent.
    
    Args:
        agent_id: The ID of the agent
        
    Returns:
        List of tasks and count
    """
    url = f"{API_BASE_URL}/tasks/agent/{agent_id}"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving tasks for agent {agent_id}: {e}")
        if hasattr(e, "response") and e.response:
            print(f"Response: {e.response.text}")
        raise


def get_task_by_id(task_id: str) -> Dict[str, Any]:
    """
    Retrieve a specific task by its ID.
    
    Args:
        task_id: The ID of the task
        
    Returns:
        The task data
    """
    url = f"{API_BASE_URL}/tasks/{task_id}"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving task {task_id}: {e}")
        if hasattr(e, "response") and e.response:
            print(f"Response: {e.response.text}")
        raise


def print_json(data: Dict[str, Any]) -> None:
    """Print JSON data in a readable format."""
    print(json.dumps(data, indent=2))


def run_examples():
    """Run the task assignment examples."""
    print("=== AgentArea Task Assignment Examples ===\n")
    
    # Generate test IDs
    user_id = generate_id()
    agent_id = generate_id()
    
    print(f"Using test user ID: {user_id}")
    print(f"Using test agent ID: {agent_id}")
    print("\n")
    
    # Example 1: Create a task assigned to a user
    print("Example 1: Creating a task assigned to a user...")
    user_task = create_task(
        message="This is a task assigned to a user",
        user_id=user_id,
        metadata={"priority": "high", "category": "test"}
    )
    print("Task created:")
    print_json(user_task)
    print("\n")
    
    # Example 2: Create a task assigned to an agent
    print("Example 2: Creating a task assigned to an agent...")
    agent_task = create_task(
        message="This is a task assigned to an agent",
        agent_id=agent_id,
        metadata={"priority": "medium", "category": "test"}
    )
    print("Task created:")
    print_json(agent_task)
    print("\n")
    
    # Example 3: Create a task assigned to both user and agent
    print("Example 3: Creating a task assigned to both user and agent...")
    combined_task = create_task(
        message="This is a task assigned to both user and agent",
        user_id=user_id,
        agent_id=agent_id,
        metadata={"priority": "low", "category": "test"}
    )
    print("Task created:")
    print_json(combined_task)
    print("\n")
    
    # Give the server a moment to process the tasks
    print("Waiting for tasks to be processed...")
    time.sleep(1)
    
    # Example 4: Retrieve tasks by user ID
    print("Example 4: Retrieving tasks by user ID...")
    user_tasks = get_tasks_by_user(user_id)
    print(f"Found {user_tasks['count']} tasks for user {user_id}:")
    print_json(user_tasks)
    print("\n")
    
    # Example 5: Retrieve tasks by agent ID
    print("Example 5: Retrieving tasks by agent ID...")
    agent_tasks = get_tasks_by_agent(agent_id)
    print(f"Found {agent_tasks['count']} tasks for agent {agent_id}:")
    print_json(agent_tasks)
    print("\n")
    
    # Example 6: Retrieve a specific task by ID
    print("Example 6: Retrieving a specific task by ID...")
    task_id = combined_task["id"]
    task = get_task_by_id(task_id)
    print(f"Retrieved task {task_id}:")
    print_json(task)
    print("\n")
    
    print("=== Examples completed successfully ===")


if __name__ == "__main__":
    try:
        run_examples()
    except Exception as e:
        print(f"Error running examples: {e}")
        exit(1)
