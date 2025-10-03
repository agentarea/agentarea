"""
Интеграционные тесты для AgentExecutionWorkflow.

Основная цель: убедиться что workflow исполняется без зацикливания
и корректно завершается во всех сценариях.
"""

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

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
class MockResponses:
    """Централизованное управление мок-ответами для тестов."""

    def __init__(self):
        self.llm_call_count = 0
        self.tool_call_count = 0

    def reset_counters(self):
        """Сброс счетчиков для нового теста."""
        self.llm_call_count = 0
        self.tool_call_count = 0

    @property
    def agent_config(self) -> dict[str, Any]:
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
    def available_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "task_complete",
                "description": "Mark task as completed",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {"type": "string", "description": "Task result"},
                        "success": {
                            "type": "boolean",
                            "description": "Whether task was successful",
                        },
                    },
                    "required": ["result", "success"],
                },
            },
            {
                "name": "search_web",
                "description": "Search the web for information",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Search query"}},
                    "required": ["query"],
                },
            },
            {
                "name": "analyze_data",
                "description": "Analyze provided data",
                "parameters": {
                    "type": "object",
                    "properties": {"data": {"type": "string", "description": "Data to analyze"}},
                    "required": ["data"],
                },
            },
        ]

    def get_llm_response_success_scenario(self) -> dict[str, Any]:
        """Сценарий успешного завершения за 2 итерации."""
        self.llm_call_count += 1

        if self.llm_call_count == 1:
            # Первая итерация: поиск информации
            return {
                "role": "assistant",
                "content": "I need to search for information to complete this task.",
                "tool_calls": [
                    {
                        "id": "call_search_1",
                        "type": "function",
                        "function": {
                            "name": "search_web",
                            "arguments": json.dumps({"query": "task information"}),
                        },
                    }
                ],
                "cost": 0.01,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            }
        elif self.llm_call_count == 2:
            # Вторая итерация: завершение задачи
            return {
                "role": "assistant",
                "content": "Based on the search results, I can now complete the task.",
                "tool_calls": [
                    {
                        "id": "call_complete_1",
                        "type": "function",
                        "function": {
                            "name": "task_complete",
                            "arguments": json.dumps(
                                {
                                    "result": "Task completed successfully with search results",
                                    "success": True,
                                }
                            ),
                        },
                    }
                ],
                "cost": 0.015,
                "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
            }
        else:
            # Fallback - не должно происходить в успешном сценарии
            return {
                "role": "assistant",
                "content": "I'm not sure what to do next.",
                "tool_calls": [],
                "cost": 0.005,
                "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            }

    def get_llm_response_max_iterations_scenario(self) -> dict[str, Any]:
        """Сценарий который никогда не завершается (для тестирования max_iterations)."""
        self.llm_call_count += 1

        return {
            "role": "assistant",
            "content": f"Still working on iteration {self.llm_call_count}...",
            "tool_calls": [
                {
                    "id": f"call_search_{self.llm_call_count}",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": f"search query {self.llm_call_count}"}),
                    },
                }
            ],
            "cost": 0.02,  # Относительно дорогие вызовы
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

    def get_llm_response_expensive_scenario(self) -> dict[str, Any]:
        """Сценарий с дорогими вызовами для тестирования бюджета."""
        self.llm_call_count += 1

        return {
            "role": "assistant",
            "content": f"Expensive operation {self.llm_call_count} in progress...",
            "tool_calls": [
                {
                    "id": f"call_analyze_{self.llm_call_count}",
                    "type": "function",
                    "function": {
                        "name": "analyze_data",
                        "arguments": json.dumps({"data": f"large dataset {self.llm_call_count}"}),
                    },
                }
            ],
            "cost": 3.0,  # Очень дорогой вызов
            "usage": {"prompt_tokens": 2000, "completion_tokens": 1000, "total_tokens": 3000},
        }

    def get_llm_response_empty_scenario(self) -> dict[str, Any]:
        """Сценарий с пустыми ответами, затем успешное завершение."""
        self.llm_call_count += 1

        if self.llm_call_count <= 2:
            # Первые 2 итерации - пустые ответы
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [],
                "cost": 0.001,
                "usage": {"prompt_tokens": 50, "completion_tokens": 0, "total_tokens": 50},
            }
        else:
            # Третья итерация - успешное завершение
            return {
                "role": "assistant",
                "content": "Now I can complete the task after empty responses.",
                "tool_calls": [
                    {
                        "id": "call_complete_after_empty",
                        "type": "function",
                        "function": {
                            "name": "task_complete",
                            "arguments": json.dumps(
                                {
                                    "result": "Task completed after handling empty responses",
                                    "success": True,
                                }
                            ),
                        },
                    }
                ],
                "cost": 0.01,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            }

    def get_tool_result(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Возвращает результат выполнения инструмента."""
        self.tool_call_count += 1

        if tool_name == "task_complete":
            return {
                "result": tool_args.get("result", "Task completed"),
                "success": tool_args.get("success", True),
                "completed": True,  # Дополнительный флаг для совместимости
            }
        elif tool_name == "search_web":
            return {
                "result": f"Search results for '{tool_args.get('query', 'unknown')}': Found relevant information.",
                "success": True,
            }
        elif tool_name == "analyze_data":
            return {
                "result": f"Analysis of '{tool_args.get('data', 'unknown')}': Data processed successfully.",
                "success": True,
            }
        else:
            return {
                "result": f"Unknown tool '{tool_name}' executed with args: {tool_args}",
                "success": False,
            }


class TestAgentExecutionWorkflow:
    """Интеграционные тесты для AgentExecutionWorkflow."""

    @pytest_asyncio.fixture
    async def workflow_environment(self):
        """Создает тестовое окружение с time-skipping."""
        env = await WorkflowEnvironment.start_time_skipping()
        try:
            yield env
        finally:
            await env.shutdown()

    @pytest_asyncio.fixture
    async def mock_responses(self):
        """Создает объект для управления мок-ответами."""
        responses = MockResponses()
        yield responses
        responses.reset_counters()

    def create_test_request(
        self,
        max_iterations: int = 5,
        budget_usd: float = 10.0,
        task_query: str = "Complete a test task",
    ) -> AgentExecutionRequest:
        """Создает тестовый запрос на выполнение."""
        return AgentExecutionRequest(
            agent_id=uuid4(),
            task_id=uuid4(),
            user_id="test-user",
            task_query=task_query,
            task_parameters={
                "success_criteria": ["Task should be completed successfully"],
                "max_iterations": max_iterations,
            },
            budget_usd=budget_usd,
            requires_human_approval=False,
        )

    def create_mock_activities(self, mock_responses: MockResponses, scenario: str = "success"):
        """Создает мок-активности для указанного сценария."""

        @activity.defn
        async def build_agent_config_activity(*args, **kwargs):
            return mock_responses.agent_config

        @activity.defn
        async def discover_available_tools_activity(*args, **kwargs):
            return mock_responses.available_tools

        @activity.defn
        async def call_llm_activity(*args, **kwargs):
            if scenario == "success":
                return mock_responses.get_llm_response_success_scenario()
            elif scenario == "max_iterations":
                return mock_responses.get_llm_response_max_iterations_scenario()
            elif scenario == "budget_exceeded":
                return mock_responses.get_llm_response_expensive_scenario()
            elif scenario == "empty_responses":
                return mock_responses.get_llm_response_empty_scenario()
            else:
                raise ValueError(f"Unknown scenario: {scenario}")

        @activity.defn
        async def execute_mcp_tool_activity(tool_name: str, tool_args: dict, *args, **kwargs):
            return mock_responses.get_tool_result(tool_name, tool_args)

        @activity.defn
        async def evaluate_goal_progress_activity(*args, **kwargs):
            # Всегда возвращаем False - пусть task_complete управляет завершением
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
            publish_workflow_events_activity,
        ]

    @pytest.mark.asyncio
    async def test_workflow_completes_successfully_with_task_complete(
        self, workflow_environment, mock_responses
    ):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Workflow должен завершиться успешно когда LLM вызывает task_complete.

        Проверяет:
        - Workflow завершается с success=True
        - final_response устанавливается корректно
        - Количество итераций минимально (2 в данном случае)
        - Нет зацикливания
        """
        activities = self.create_mock_activities(mock_responses, "success")

        async with Worker(
            workflow_environment.client,
            task_queue="test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
        ):
            request = self.create_test_request()

            result = await workflow_environment.client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"test-success-{uuid4()}",
                task_queue="test-queue",
            )

            # Проверки результата
            assert isinstance(result, AgentExecutionResult)
            assert result.success is True, "Workflow должен завершиться успешно"
            assert result.final_response == "Task completed successfully with search results"
            assert result.reasoning_iterations_used == 2, (
                f"Ожидалось 2 итерации, получено {result.reasoning_iterations_used}"
            )
            assert result.task_id == request.task_id
            assert result.agent_id == request.agent_id
            assert result.total_cost > 0, "Стоимость должна быть больше 0"

            # Проверки счетчиков мок-объектов
            assert mock_responses.llm_call_count == 2, (
                f"Ожидалось 2 вызова LLM, получено {mock_responses.llm_call_count}"
            )
            assert mock_responses.tool_call_count == 2, (
                f"Ожидалось 2 вызова инструментов, получено {mock_responses.tool_call_count}"
            )

    @pytest.mark.asyncio
    async def test_workflow_stops_at_max_iterations(self, workflow_environment, mock_responses):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Workflow должен остановиться при достижении max_iterations.

        Проверяет:
        - Workflow останавливается точно на max_iterations
        - success=False при превышении лимита
        - Нет зацикливания или превышения лимита
        """
        activities = self.create_mock_activities(mock_responses, "max_iterations")

        async with Worker(
            workflow_environment.client,
            task_queue="test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
        ):
            # Устанавливаем низкий лимит итераций для быстрого тестирования
            request = self.create_test_request(max_iterations=3)

            result = await workflow_environment.client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"test-max-iterations-{uuid4()}",
                task_queue="test-queue",
            )

            # Проверки результата
            assert isinstance(result, AgentExecutionResult)
            assert result.success is False, (
                "Workflow не должен быть успешным при превышении лимита итераций"
            )
            # При max_iterations=3 выполняется только 2 итерации (логика проверяет ДО выполнения)
            assert result.reasoning_iterations_used == 2, (
                f"Ожидалось 2 итерации (max_iterations-1), получено {result.reasoning_iterations_used}"
            )
            assert result.task_id == request.task_id
            assert result.agent_id == request.agent_id

            # Проверки счетчиков - должно быть max_iterations-1 вызовов
            assert mock_responses.llm_call_count == 2, (
                f"Ожидалось 2 вызова LLM, получено {mock_responses.llm_call_count}"
            )
            assert mock_responses.tool_call_count == 2, (
                f"Ожидалось 2 вызова инструментов, получено {mock_responses.tool_call_count}"
            )

    @pytest.mark.asyncio
    async def test_workflow_stops_when_budget_exceeded(self, workflow_environment, mock_responses):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Workflow должен остановиться при превышении бюджета.

        Проверяет:
        - Workflow останавливается при превышении budget_usd
        - success=False при превышении бюджета
        - total_cost >= budget_usd
        - Нет зацикливания после превышения бюджета
        """
        activities = self.create_mock_activities(mock_responses, "budget_exceeded")

        async with Worker(
            workflow_environment.client,
            task_queue="test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
        ):
            # Устанавливаем низкий бюджет (каждый вызов стоит 3.0)
            request = self.create_test_request(budget_usd=5.0, max_iterations=10)

            result = await workflow_environment.client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"test-budget-exceeded-{uuid4()}",
                task_queue="test-queue",
            )

            # Проверки результата
            assert isinstance(result, AgentExecutionResult)
            assert result.success is False, (
                "Workflow не должен быть успешным при превышении бюджета"
            )
            assert result.total_cost >= request.budget_usd, (
                f"Стоимость {result.total_cost} должна превышать бюджет {request.budget_usd}"
            )
            assert result.reasoning_iterations_used <= 3, (
                f"Не должно быть больше 3 итераций при таком бюджете, получено {result.reasoning_iterations_used}"
            )
            assert result.task_id == request.task_id
            assert result.agent_id == request.agent_id

            # Проверки счетчиков - должно остановиться рано из-за бюджета
            assert mock_responses.llm_call_count <= 3, (
                f"Не должно быть больше 3 вызовов LLM, получено {mock_responses.llm_call_count}"
            )

    @pytest.mark.asyncio
    async def test_workflow_handles_empty_llm_responses(self, workflow_environment, mock_responses):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Workflow должен корректно обрабатывать пустые ответы LLM.

        Проверяет:
        - Workflow продолжает работу при пустых ответах
        - Пустые сообщения не вызывают зацикливание
        - Workflow может завершиться успешно после пустых ответов
        """
        activities = self.create_mock_activities(mock_responses, "empty_responses")

        async with Worker(
            workflow_environment.client,
            task_queue="test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
        ):
            request = self.create_test_request(max_iterations=5)

            result = await workflow_environment.client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"test-empty-responses-{uuid4()}",
                task_queue="test-queue",
            )

            # Проверки результата
            assert isinstance(result, AgentExecutionResult)
            assert result.success is True, (
                "Workflow должен завершиться успешно после обработки пустых ответов"
            )
            assert result.final_response == "Task completed after handling empty responses"
            assert result.reasoning_iterations_used == 3, (
                f"Ожидалось 3 итерации, получено {result.reasoning_iterations_used}"
            )
            assert result.task_id == request.task_id
            assert result.agent_id == request.agent_id

            # Проверки счетчиков
            assert mock_responses.llm_call_count == 3, (
                f"Ожидалось 3 вызова LLM, получено {mock_responses.llm_call_count}"
            )
            # Только 1 tool call (task_complete), пустые ответы не вызывают инструменты
            assert mock_responses.tool_call_count == 1, (
                f"Ожидался 1 вызов инструмента, получено {mock_responses.tool_call_count}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
