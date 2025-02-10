from langchain.agents import tool
import requests
from typing import Dict, List

BASE_URL = "http://localhost:8000"


@tool
def get_available_agents() -> Dict:
    """Получает список доступных агентов и их спецификации"""
    print("Вызвана функция get_available_agents")
    try:
        response = requests.get(f"{BASE_URL}/modules/", timeout=5)
        response.raise_for_status()
        print(f"Получен ответ от сервера: {response.text}")
        return response.json()
    except requests.exceptions.RequestException as e:
        error_msg = f"Ошибка при запросе к серверу: {str(e)}"
        print(error_msg)
        # Возвращаем тестовые данные, если сервер недоступен
        return {
            "test_agent": {
                "description": "Тестовый агент для отладки",
                "capabilities": ["test1", "test2"],
                "input_format": "text",
                "output_format": "text",
            }
        }


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
    return [get_available_agents]
