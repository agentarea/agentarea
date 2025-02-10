from langchain.agents import tool
import requests
from typing import Dict, List, Optional
import json
from confluent_kafka import Producer
import uuid
import datetime

BASE_URL = "http://localhost:8000"

# Добавим конфигурацию Kafka продюсера
KAFKA_CONFIG = {
    "bootstrap.servers": "localhost:9092",
}


@tool
def get_available_agents() -> Dict:
    """Получает список доступных агентов и их спецификации"""
    print("Вызвана функция get_available_agents")
    try:
        response = requests.get(f"{BASE_URL}/modules/", timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к серверу: {str(e)}")
        return {
            "test_agent": {
                "description": "Тестовый агент для отладки",
                "capabilities": ["test1", "test2"],
                "input_format": "text",
                "output_format": "text",
            }
        }


@tool
def execute_agent_task(agent_id: str, task_input: Dict) -> Dict:
    """Отправляет задачу агенту через Kafka

    Args:
        agent_id: Идентификатор агента
        task_input: Входные данные для задачи

    Returns:
        Dict с execution_id для отслеживания выполнения задачи
    """
    try:
        # Создаем уникальный execution_id
        execution_id = str(uuid.uuid4())

        # Создаем продюсера
        producer = Producer(KAFKA_CONFIG)

        # Формируем топик для агента
        topic = f"execution_{execution_id}_{agent_id}"

        # Подготавливаем сообщение
        message = {
            "execution_id": execution_id,
            "agent_id": agent_id,
            "task_input": task_input,
            "timestamp": datetime.datetime.now().isoformat(),
        }

        # Отправляем сообщение
        producer.produce(
            topic,
            value=json.dumps(message).encode("utf-8"),
            callback=lambda err, msg: (
                print(f"Сообщение доставлено: {msg}") if err is None else print(f"Ошибка: {err}")
            ),
        )

        # Ожидаем отправки всех сообщений
        producer.flush()

        return {
            "status": "task_sent",
            "execution_id": execution_id,
            "agent_id": agent_id,
            "topic": topic,
        }

    except Exception as e:
        print(f"Ошибка при отправке задачи агенту: {str(e)}")
        return {"status": "error", "message": str(e)}


@tool
def evaluate_task_completion(context: Dict) -> Dict:
    """Оценивает, выполнена ли бизнес-задача на основе текущего контекста"""
    # Здесь может быть более сложная логика оценки выполнения задачи
    required_fields = context.get("required_fields", [])
    current_fields = set(context.keys())

    missing_fields = [field for field in required_fields if field not in current_fields]

    return {"is_completed": len(missing_fields) == 0, "missing_fields": missing_fields}


def format_agents_specs(agents: Dict) -> str:
    """Форматирует спецификации агентов для включения в промпт"""
    formatted_specs = []
    for agent_name, specs in agents.items():
        formatted_specs.append(
            f"""
Агент: {agent_name}
Описание: {specs.get('description', 'Нет описания')}
Возможности: {', '.join(specs.get('capabilities', []))}
Входные данные: {specs.get('input_format', 'Не указано')}
Выходные данные: {specs.get('output_format', 'Не указано')}
"""
        )
    return "\n".join(formatted_specs)


def get_tools() -> List:
    """Возвращает список инструментов для агента"""
    return [get_available_agents, execute_agent_task, evaluate_task_completion]
