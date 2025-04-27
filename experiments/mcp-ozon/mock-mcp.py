import asyncio
import logging
from typing import Dict, List, Any, Optional
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastMCP instance
mcp = FastMCP()

# Mock data store
tasks = {
    1: {"id": 1, "title": "Buy groceries", "completed": False},
    2: {"id": 2, "title": "Clean house", "completed": True},
    3: {"id": 3, "title": "Finish project", "completed": False}
}
next_id = 4

@mcp.tool(name="listTasks")
def list_tasks() -> Dict[str, Any]:
    """List all available tasks."""
    return {
        "status": "success",
        "tasks": list(tasks.values())
    }

@mcp.tool(name="addTask")
def add_task(title: str, completed: bool = False) -> Dict[str, Any]:
    """
    Add a new task to the list.
    
    Args:
        title: The title of the task
        completed: Whether the task is completed (default: False)
    """
    global next_id
    task_id = next_id
    next_id += 1
    
    new_task = {
        "id": task_id,
        "title": title,
        "completed": completed
    }
    
    tasks[task_id] = new_task
    
    return {
        "status": "success",
        "message": "Task added successfully",
        "task": new_task
    }

@mcp.tool(name="toggleTaskStatus")
def toggle_task_status(task_id: int) -> Dict[str, Any]:
    """
    Toggle the completion status of a task.
    
    Args:
        task_id: The ID of the task to toggle
    """
    if task_id not in tasks:
        return {
            "status": "error",
            "message": f"Task with ID {task_id} not found"
        }
    
    tasks[task_id]["completed"] = not tasks[task_id]["completed"]
    
    return {
        "status": "success",
        "message": f"Task status toggled to {tasks[task_id]['completed']}",
        "task": tasks[task_id]
    }

@mcp.tool(name="deleteTask")
def delete_task(task_id: int) -> Dict[str, Any]:
    """
    Delete a task from the list.
    
    Args:
        task_id: The ID of the task to delete
    """
    if task_id not in tasks:
        return {
            "status": "error",
            "message": f"Task with ID {task_id} not found"
        }
    
    deleted_task = tasks.pop(task_id)
    
    return {
        "status": "success",
        "message": "Task deleted successfully",
        "deleted_task": deleted_task
    }

@mcp.tool()
def server_info() -> Dict[str, Any]:
    """Get information about this mock MCP server."""
    return {
        "name": "Mock MCP Task Server",
        "description": "A simple MCP server for task management",
        "tools_count": 5,
        "tasks_count": len(tasks)
    }

if __name__ == "__main__":
    logger.info("Starting Mock MCP server")
    logger.info("Server ready to accept connections")
    mcp.run(transport="sse", host="127.0.0.1", port=3001)
