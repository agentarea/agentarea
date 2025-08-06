"""
ФИНАЛЬНЫЙ ТЕСТ: Проверка что AgentExecutionWorkflow не зацикливается.

Этот тест подтверждает что ваш workflow исполняется корректно
и завершается во всех основных сценариях.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from libs.execution.agentarea_execution.models import (
    AgentExecutionRequest,
    AgentExecutionResult,
)
from libs.execution.agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)


@dataclass
class TestData:
    """Тестовые данные для workflow."""
    
    @property
    def agent_config(self) -> Dict[str, Any]:
        return {
            "id": "test-agent-id",
            "name": "Test Agent",
            "description": "Test agent for workflow testing",
            "instruction": "Complete the given task efficiently",
            "model_id": "test-model-id",
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }
    
    @property
    def available_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "task_complete",
                "description": "Mark task as completed",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {"type": "string", "description": "Task result"},
                        "success": {"type": "boolean", "description": "Whether task was successful"}
                    },
                    "required": ["result", "success"]
                }
            }
        ]


class TestAgentExecutionWorkflowFinal:
    """Финальные тесты workflow."""
    
    @pytest_asyncio.fixture
    async def workflow_environment(self):
        """Создает тестовое окружение."""
        env = await WorkflowEnvironment.start_time_skipping()
        try:
            yield env
        finally:
            await env.shutdown()
    
    def create_test_request(self, max_iterations: int = 3) -> AgentExecutionRequest:
        """Создает тестовый запрос."""
        return AgentExecutionRequest(
            agent_id=uuid4(),
            task_id=uuid4(),
            user_id="test-user",
            task_query="Complete a simple test task",
            task_parameters={
                "success_criteria": ["Task should be completed successfully"],
                "max_iterations": max_iterations
            },
            budget_usd=5.0,
            requires_human_approval=False
        )
    
    def create_activities(self, test_data: TestData):
        """Создает мок-активности."""
        call_count = 0
        
        @activity.defn
        async def build_agent_config_activity(*args, **kwargs):
            return test_data.agent_config
        
        @activity.defn
        async def discover_available_tools_activity(*args, **kwargs):
            return test_data.available_tools
        
        @activity.defn
        async def call_llm_activity(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            # На первом вызове завершаем задачу
            return {
                "role": "assistant",
                "content": "I will complete this task now.",
                "tool_calls": [
                    {
                        "id": f"call_complete_{call_count}",
                        "type": "function",
                        "function": {
                            "name": "task_complete",
                            "arguments": json.dumps({
                                "result": f"Task completed successfully on call {call_count}",
                                "success": True
                            })
                        }
                    }
                ],
                "cost": 0.01,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
            }
        
        @activity.defn
        async def execute_mcp_tool_activity(tool_name: str, tool_args: dict, *args, **kwargs):
            if tool_name == "task_complete":
                return {
                    "result": tool_args.get("result", "Task completed"),
                    "success": tool_args.get("success", True),
                    "completed": True
                }
            return {"result": "Unknown tool", "success": False}
        
        @activity.defn
        async def evaluate_goal_progress_activity(*args, **kwargs):
            return {"goal_achieved": False, "final_response": None, "confidence": 0.5}
        
        @activity.defn
        async def publish_workflow_events_activity(*args, **kwargs):
            return True
        
        return [
            build_agent_config_activity,
            discover_available_tools_activity,
            call_llm_activity,
            execute_mcp_tool_activity,
            evaluate_goal_progress_activity,
            publish_workflow_events_activity
        ]
    
    @pytest.mark.asyncio
    async def test_workflow_completes_successfully(self, workflow_environment):
        """
        🎯 ГЛАВНЫЙ ТЕСТ: Workflow завершается успешно и НЕ ЗАЦИКЛИВАЕТСЯ.
        """
        test_data = TestData()
        activities = self.create_activities(test_data)
        
        async with Worker(
            workflow_environment.client,
            task_queue="final-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities
        ):
            request = self.create_test_request()
            
            print(f"\n🚀 Запуск workflow с задачей: {request.task_query}")
            
            result = await workflow_environment.client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"final-test-{uuid4()}",
                task_queue="final-test-queue"
            )
            
            # Проверки результата
            assert isinstance(result, AgentExecutionResult)
            print(f"✅ Workflow завершен: success={result.success}")
            print(f"📊 Итераций: {result.reasoning_iterations_used}")
            print(f"💰 Стоимость: ${result.total_cost}")
            print(f"📝 Ответ: {result.final_response}")
            
            # Основные проверки
            assert result.success is True, "Workflow должен завершиться успешно"
            assert result.reasoning_iterations_used == 1, "Должна быть 1 итерация"
            assert result.final_response is not None, "Должен быть финальный ответ"
            assert result.task_id == request.task_id
            assert result.agent_id == request.agent_id
            
            print("🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
            print("🚫 ЗАЦИКЛИВАНИЯ НЕТ!")
            print("✅ WORKFLOW РАБОТАЕТ КОРРЕКТНО!")
    
    @pytest.mark.asyncio
    async def test_workflow_stops_at_max_iterations(self, workflow_environment):
        """
        🛑 ТЕСТ ОГРАНИЧЕНИЙ: Workflow останавливается при достижении лимита итераций.
        """
        test_data = TestData()
        call_count = 0
        
        @activity.defn
        async def build_agent_config_activity(*args, **kwargs):
            return test_data.agent_config
        
        @activity.defn
        async def discover_available_tools_activity(*args, **kwargs):
            return test_data.available_tools
        
        @activity.defn
        async def call_llm_activity(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            # Никогда не завершаем задачу - тестируем лимит итераций
            return {
                "role": "assistant",
                "content": f"Still working on iteration {call_count}...",
                "tool_calls": [],  # Никаких tool calls
                "cost": 0.01,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
            }
        
        @activity.defn
        async def execute_mcp_tool_activity(tool_name: str, tool_args: dict, *args, **kwargs):
            return {"result": "Should not be called", "success": False}
        
        @activity.defn
        async def evaluate_goal_progress_activity(*args, **kwargs):
            return {"goal_achieved": False, "final_response": None, "confidence": 0.5}
        
        @activity.defn
        async def publish_workflow_events_activity(*args, **kwargs):
            return True
        
        activities = [
            build_agent_config_activity,
            discover_available_tools_activity,
            call_llm_activity,
            execute_mcp_tool_activity,
            evaluate_goal_progress_activity,
            publish_workflow_events_activity
        ]
        
        async with Worker(
            workflow_environment.client,
            task_queue="final-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities
        ):
            request = self.create_test_request(max_iterations=2)  # Низкий лимит
            
            print(f"\n🛑 Тест лимита итераций: max_iterations={request.task_parameters['max_iterations']}")
            
            result = await workflow_environment.client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"final-limit-test-{uuid4()}",
                task_queue="final-test-queue"
            )
            
            # Проверки результата
            assert isinstance(result, AgentExecutionResult)
            print(f"🛑 Workflow остановлен: success={result.success}")
            print(f"📊 Итераций: {result.reasoning_iterations_used}")
            print(f"🔢 LLM вызовов: {call_count}")
            
            # Основные проверки
            assert result.success is False, "Workflow не должен быть успешным при превышении лимита"
            assert result.reasoning_iterations_used <= 1, "Должно быть не больше 1 итерации (max-1)"
            assert call_count <= 2, "Не должно быть больше 2 вызовов LLM"
            
            print("🎉 ЛИМИТ ИТЕРАЦИЙ РАБОТАЕТ!")
            print("🚫 ЗАЦИКЛИВАНИЯ НЕТ!")
            print("✅ ОГРАНИЧЕНИЯ РАБОТАЮТ КОРРЕКТНО!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])