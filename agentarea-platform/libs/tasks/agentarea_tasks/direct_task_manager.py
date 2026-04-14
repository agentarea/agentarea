"""Direct task manager — runs agent execution in-process without Temporal.

Same BaseTaskManager interface and same dependency chain as TemporalTaskManager.
The agent's model, skills, and tools are resolved from the database —
same as the Temporal workflow does via activities, but called directly.

Swap via WORKFLOW__EXECUTION_ENGINE=direct. No other config needed.
"""

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from .domain.interfaces import BaseTaskManager
from .domain.models import SimpleTask
from .infrastructure.repository import TaskRepository

logger = logging.getLogger(__name__)


class DirectTaskManager(BaseTaskManager):
    """Task manager that runs agent execution directly in-process.

    Same constructor signature as TemporalTaskManager — takes TaskRepository.
    Resolves agent config, model, skills from DB, same as the workflow would.
    """

    def __init__(self, task_repository: TaskRepository):
        self.task_repository = task_repository
        self._tasks: dict[UUID, SimpleTask] = {}

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit and immediately execute a task in-process."""
        logger.info(f"DirectTaskManager: executing task {task.id} in-process")

        task.status = "running"
        task.execution_id = f"task-{task.id}"
        self._tasks[task.id] = task

        # Update status in DB
        await self.task_repository.update_status(task.id, "running")

        # Execute synchronously
        await self._execute(task)

        return task

    async def _execute(self, task: SimpleTask) -> None:
        """Run the agent loop using DB-resolved config, same as Temporal workflow."""
        try:
            # Resolve agent config from DB — same chain as build_agent_config_activity
            llm, instruction, skills_data = await self._resolve_agent(task)

            # Run agent loop
            from agentarea_agents_sdk.models.llm_model import LLMRequest
            from agentarea_agents_sdk.skills import (
                SkillActivationTool,
                SkillCatalogBuilder,
                SkillEntry,
            )

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

            tools = []
            if skill_tool:
                tools.append(skill_tool.get_openai_function_definition())
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "completion",
                        "description": "Present your final answer to the user. The 'result' parameter is the message the user will read — write a complete, helpful response (not just a status like 'done').",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "result": {"type": "string", "description": "Your complete response to the user. This text is shown directly to them."},
                            },
                            "required": ["result"],
                        },
                    },
                }
            )

            messages = [
                {"role": "system", "content": f"{instruction}{catalog_text}"},
                {"role": "user", "content": task.query},
            ]

            max_iterations = 10
            for iteration in range(1, max_iterations + 1):
                logger.info(f"DirectTaskManager: iteration {iteration}")

                response = await llm.complete(
                    LLMRequest(
                        messages=messages,
                        tools=tools,
                        temperature=0.1,
                    )
                )

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content or "",
                }
                if response.tool_calls:
                    assistant_msg["tool_calls"] = response.tool_calls
                messages.append(assistant_msg)

                if not response.tool_calls:
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
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": "activate_skill",
                                "content": result.get("result", ""),
                            }
                        )
                    elif fn_name == "completion":
                        task.status = "completed"
                        task.result = {"response": fn_args.get("result", "")}
                        break
                    else:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": fn_name,
                                "content": f"Unknown tool: {fn_name}",
                            }
                        )

                if task.status == "completed":
                    break
            else:
                task.status = "completed"
                task.result = {"response": messages[-1].get("content", "Max iterations reached")}

            # Persist result to DB
            await self.task_repository.update_status(
                task.id,
                task.status,
                result=task.result,
            )
            self._tasks[task.id] = task

        except Exception as e:
            logger.error(f"DirectTaskManager: execution failed: {e}")
            task.status = "failed"
            task.result = {"error": str(e)}
            await self.task_repository.update_status(
                task.id,
                "failed",
                error_message=str(e),
            )
            self._tasks[task.id] = task

    async def _resolve_agent(self, task: SimpleTask):
        """Resolve agent config from DB — same chain as build_agent_config_activity.

        Returns (LLMModel, instruction, skills_data).
        """
        from agentarea_agents_sdk.models.llm_model import LLMModel
        from agentarea_common.auth.context import UserContext

        # Get services via DI container
        from agentarea_common.di.container import get_container

        container = get_container()

        user_context = UserContext(
            user_id=task.user_id,
            workspace_id=task.workspace_id,
        )

        # Resolve agent
        agent_service, session = await container.get_agent_service(user_context)
        agent = await agent_service.get_with_skills(task.agent_id)
        if not agent:
            raise ValueError(f"Agent {task.agent_id} not found")

        instruction = agent.instruction or "You are a helpful AI assistant."

        # Resolve skills
        skills_data = []
        if hasattr(agent, "skills") and agent.skills:
            for skill in agent.skills:
                skills_data.append(
                    {
                        "name": skill.name,
                        "description": skill.description or "",
                        "content": skill.content or "",
                        "files": [],
                    }
                )

        # Resolve model instance → provider config → API key
        model_instance_service, _ = await container.get_model_instance_service(user_context)
        model_instance = await model_instance_service.get(UUID(agent.model_id))
        if not model_instance:
            raise ValueError(f"Model instance {agent.model_id} not found")

        provider_type = model_instance.provider_config.provider_spec.provider_type
        model_name = model_instance.model_spec.model_name

        # Get API key from secret manager
        secret_manager = await container.get_secret_manager(task.workspace_id)
        api_key_secret = model_instance.provider_config.api_key_secret_name
        api_key = await secret_manager.get_secret(api_key_secret) if api_key_secret else ""

        endpoint_url = (
            model_instance.provider_config.endpoint_url or model_instance.model_spec.endpoint_url
        )

        llm = LLMModel(
            provider_type=provider_type,
            model_name=model_name,
            api_key=api_key,
            endpoint_url=endpoint_url,
        )

        logger.info(
            f"DirectTaskManager: resolved {provider_type}/{model_name} for agent {agent.name}"
        )

        await session.close()
        return llm, instruction, skills_data

    # --- BaseTaskManager interface ---

    async def get_task(self, task_id: UUID) -> SimpleTask | None:
        task = self._tasks.get(task_id)
        if task:
            return task
        task_domain = await self.task_repository.get_task(task_id)
        if task_domain:
            return self._task_to_simple_task(task_domain)
        return None

    async def cancel_task(self, task_id: UUID) -> bool:
        logger.warning(f"DirectTaskManager: cancel not supported for {task_id}")
        return False

    async def list_tasks(
        self,
        agent_id=None,
        user_id=None,
        status=None,
        limit=100,
        offset=0,
    ) -> list[SimpleTask]:
        tasks = await self.task_repository.list_tasks(limit=limit, offset=offset)
        return [self._task_to_simple_task(t) for t in tasks]

    async def get_task_status(self, task_id: UUID) -> str | None:
        task = await self.get_task(task_id)
        return task.status if task else None

    async def get_task_result(self, task_id: UUID) -> Any | None:
        task = await self.get_task(task_id)
        return task.result if task else None

    def _task_to_simple_task(self, task) -> SimpleTask:
        return SimpleTask(
            id=task.id,
            title=getattr(task, "title", ""),
            description=getattr(task, "description", ""),
            query=getattr(task, "query", task.description),
            user_id=str(getattr(task, "created_by", "")),
            workspace_id=str(task.workspace_id),
            agent_id=getattr(task, "agent_id", None),
            status=task.status,
            result=task.result,
            execution_id=f"task-{task.id}",
        )
