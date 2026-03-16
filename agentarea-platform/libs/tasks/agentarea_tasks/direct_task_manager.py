"""Direct task manager — runs agent execution in-process without Temporal.

Same BaseTaskManager interface, but executes the agent loop directly.
No workers, no queues, no infrastructure required.

Use cases:
- Local development without Temporal running
- Unit/integration testing
- Single-shot CLI execution
- Environments where Temporal is overkill
"""

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from .domain.interfaces import BaseTaskManager
from .domain.models import SimpleTask

logger = logging.getLogger(__name__)


class DirectTaskManager(BaseTaskManager):
    """Task manager that runs agent execution directly in-process."""

    def __init__(
        self,
        provider_type: str,
        model_name: str,
        api_key: str,
        endpoint_url: str | None = None,
        max_iterations: int = 10,
        sandbox_execute_url: str | None = None,
    ):
        self.provider_type = provider_type
        self.model_name = model_name
        self.api_key = api_key
        self.endpoint_url = endpoint_url
        self.max_iterations = max_iterations
        self.sandbox_execute_url = sandbox_execute_url
        self._tasks: dict[UUID, SimpleTask] = {}

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit and immediately execute a task in-process."""
        logger.info(f"DirectTaskManager: executing task {task.id} in-process")

        task.status = "running"
        task.execution_id = f"task-{task.id}"
        self._tasks[task.id] = task

        # Execute synchronously (no background — caller awaits completion)
        await self._execute(task)

        return task

    async def _execute(self, task: SimpleTask) -> None:
        """Run the agent loop: LLM → tools → repeat."""
        from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest
        from agentarea_agents_sdk.skills import SkillActivationTool, SkillCatalogBuilder, SkillEntry

        try:
            llm = LLMModel(
                provider_type=self.provider_type,
                model_name=self.model_name,
                api_key=self.api_key,
                endpoint_url=self.endpoint_url,
            )

            # Build skill tools if task has skills
            skills_data = (task.metadata or {}).get("skills", [])
            skill_tool = None
            catalog_text = ""
            if skills_data:
                entries = [
                    SkillEntry(
                        name=s["name"],
                        description=s.get("description", ""),
                        content=s.get("content", ""),
                        files=s.get("files", []),
                    )
                    for s in skills_data
                ]
                registry = SkillCatalogBuilder.build_registry(entries)
                skill_tool = SkillActivationTool(registry)
                catalog_text = SkillCatalogBuilder.build_catalog(entries)

            # Build tools list
            tools = []
            if skill_tool:
                tools.append(skill_tool.get_openai_function_definition())
            tools.append({
                "type": "function",
                "function": {
                    "name": "completion",
                    "description": "Signal that the task is complete",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "result": {"type": "string", "description": "Final result"},
                        },
                        "required": ["result"],
                    },
                },
            })

            instruction = (task.metadata or {}).get("instruction", "You are a helpful agent.")

            messages = [
                {"role": "system", "content": f"{instruction}{catalog_text}"},
                {"role": "user", "content": task.query},
            ]

            # Agent loop
            for iteration in range(1, self.max_iterations + 1):
                logger.info(f"DirectTaskManager: iteration {iteration}")

                response = await llm.complete(LLMRequest(
                    messages=messages, tools=tools, temperature=0.1,
                ))

                assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
                if response.tool_calls:
                    assistant_msg["tool_calls"] = response.tool_calls
                messages.append(assistant_msg)

                if not response.tool_calls:
                    # No tools called — treat as completion
                    task.status = "completed"
                    task.result = {"response": response.content or ""}
                    break

                for tc in response.tool_calls:
                    fn_name = tc["function"]["name"]
                    try:
                        fn_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        fn_args = {}
                    tc_id = tc.get("id", str(uuid4()))

                    if fn_name == "activate_skill" and skill_tool:
                        result = await skill_tool.execute(**fn_args)
                        messages.append({
                            "role": "tool", "tool_call_id": tc_id,
                            "name": "activate_skill", "content": result.get("result", ""),
                        })

                    elif fn_name == "completion":
                        task.status = "completed"
                        task.result = {"response": fn_args.get("result", "")}
                        break

                    else:
                        messages.append({
                            "role": "tool", "tool_call_id": tc_id,
                            "name": fn_name, "content": f"Unknown tool: {fn_name}",
                        })

                if task.status == "completed":
                    break
            else:
                task.status = "completed"
                task.result = {"response": "Max iterations reached"}

            self._tasks[task.id] = task
            logger.info(f"DirectTaskManager: task {task.id} completed")

        except Exception as e:
            logger.error(f"DirectTaskManager: execution failed: {e}")
            task.status = "failed"
            task.result = {"error": str(e)}
            self._tasks[task.id] = task

    async def get_task(self, task_id: UUID) -> SimpleTask | None:
        return self._tasks.get(task_id)

    async def cancel_task(self, task_id: UUID) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == "running":
            task.status = "cancelled"
            return True
        return False

    async def list_tasks(
        self, agent_id=None, user_id=None, status=None, limit=100, offset=0,
    ) -> list[SimpleTask]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks[offset:offset + limit]

    async def get_task_status(self, task_id: UUID) -> str | None:
        task = self._tasks.get(task_id)
        return task.status if task else None

    async def get_task_result(self, task_id: UUID) -> Any | None:
        task = self._tasks.get(task_id)
        return task.result if task else None
