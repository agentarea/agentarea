"""TodoList middleware for live task planning."""

from typing import Any
from uuid import UUID

from ..tasks.task_service import InMemoryTaskService
from ..tasks.tasks import TaskStatus


class TodoListMiddleware:
    """Manages TODO list in agent state using TaskService."""

    def __init__(self):
        self.task_service = InMemoryTaskService()

    async def before_llm_call(self, state: dict) -> dict[str, Any] | None:
        return None

    async def after_llm_call(self, state: dict, response) -> dict[str, Any] | None:
        return None

    async def before_tool_call(
        self, tool_call: dict, state: dict
    ) -> tuple[dict, dict[str, Any] | None]:
        if tool_call.get("function", {}).get("name") == "write_todos":
            todos = tool_call.get("function", {}).get("arguments", {}).get("todos", [])

            # Validate: reject empty todos array
            if not todos or len(todos) == 0:
                tool_call["_skip_execution"] = True
                tool_call["_result"] = {
                    "success": False,
                    "error": "Empty todos array. You must create the plan yourself by analyzing the task and breaking it into specific steps. The write_todos tool only RECORDS your plan - it does not create the plan for you. Please call write_todos() with a complete list of todos that YOU created."
                }
                return tool_call, None

            # Sync with TaskService
            for todo in todos:
                if "id" in todo and todo["id"]:
                    # Update existing
                    try:
                        self.task_service.set_status(UUID(todo["id"]), TaskStatus(todo["status"]))
                    except (ValueError, KeyError):
                        pass
                else:
                    # Create new
                    task = self.task_service.create(
                        title=todo["content"],
                        metadata={"activeForm": todo.get("activeForm", todo["content"])},
                    )
                    todo["id"] = str(task.id)

            # Skip actual tool execution (no-op tool)
            tool_call["_skip_execution"] = True

            # Format informative message for agent
            todos_summary = "\n".join([
                f"- [{todo['status']}] {todo['content']}"
                for todo in todos
            ])
            result_message = f"Updated todo list ({len(todos)} tasks):\n{todos_summary}"

            tool_call["_result"] = {
                "success": True,
                "todos_count": len(todos),
                "result": result_message  # ← Agent sees this in messages
            }

            # Return state updates
            return tool_call, {"todos": todos}

        return tool_call, None

    async def after_tool_call(
        self, tool_call: dict, result: Any, state: dict
    ) -> tuple[Any, dict[str, Any] | None]:
        return result, None
