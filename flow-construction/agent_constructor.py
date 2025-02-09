import requests
import yaml
from typing import Dict, List, Optional
import json
import os
from langchain_openai import ChatOpenAI
from langchain.tools import Tool
from langchain.agents import create_react_agent, AgentExecutor
from langchain.schema import SystemMessage
from langchain.prompts import MessagesPlaceholder, PromptTemplate
from langchain.memory import ConversationBufferMemory


class AgentConstructor:
    def __init__(self):
        self.available_agents_url = "http://localhost:8000/modules/"
        self.llm = ChatOpenAI(
            model_name="gpt-4", temperature=0.7, api_key=os.getenv("OPENAI_API_KEY")
        )
        self.memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        self.setup_tools()

    def get_available_agents(self) -> Dict:
        """Request to get available agents"""
        print("Вызвана функция get_available_agents")
        try:
            response = requests.get(self.available_agents_url, timeout=5)
            response.raise_for_status()  # Проверяем статус ответа
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

    def format_agents_specs(self, agents: Dict) -> str:
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

    def setup_tools(self):
        """Настраивает инструменты для LangChain агента"""
        self.tools = [
            Tool(
                name="GetAvailableAgents",
                func=self.get_available_agents,
                description="Получает список доступных агентов и их спецификации",
            )
        ]

        # Создаем промпт для агента
        prompt = PromptTemplate(
            template="""
            Ты - эксперт по построению мультиагентных систем.
            Твоя задача - создавать YAML-конфигурации систем на основе описания задачи.
            Выводи в консоль все свои мысли и действия.

            У тебя есть доступ к следующим инструментам:
            {tools}

            Используй следующий формат:
            Вопрос: входной вопрос, на который нужно ответить
            Мысль: ты всегда должен думать о том, что делать
            Действие: действие, которое нужно предпринять, должно быть одним из [{tool_names}]
            Входные данные действия: входные данные для действия
            Наблюдение: результат действия
            ... (этот процесс Мысль/Действие/Входные данные действия/Наблюдение может повторяться N раз)
            Мысль: Теперь я знаю окончательный ответ
            Финальный ответ: окончательный ответ на входной вопрос

            {input}

            {agent_scratchpad}
            """,
            input_variables=["input", "tools", "tool_names", "agent_scratchpad"],
        )

        # Создаем агента с новым методом
        agent = create_react_agent(llm=self.llm, tools=self.tools, prompt=prompt)

        self.agent = AgentExecutor(agent=agent, tools=self.tools, memory=self.memory, verbose=True)

    def construct_system(self, task_description: str) -> str:
        """
        Конструирует мультиагентную систему на основе описания задачи
        """
        response = self.agent.invoke(
            {
                "input": f"""
            Сначала используй инструмент GetAvailableAgents, чтобы получить список доступных агентов.
            После этого, на основе полученного списка и описания задачи, создай YAML-конфигурацию мультиагентной системы.
            
            Задача: {task_description}
            
            Конфигурация должна содержать:
            1. Список используемых агентов (выбери только из доступных агентов)
            2. Базовые промпты для каждого агента
            3. Схему коммуникации между агентами
            4. Формат данных для обмена между агентами
            
            Ответ должен быть в формате YAML.
            """
            }
        )

        try:
            output = response["output"]
            parsed_yaml = yaml.safe_load(output)
            return yaml.dump(parsed_yaml, sort_keys=False)
        except yaml.YAMLError:
            raise ValueError("LLM сгенерировал некорректный YAML")


def main():
    constructor = AgentConstructor()
    task = """Перечисли какие агенты тебе доступны?"""
    system_yaml = constructor.construct_system(task)
    print(system_yaml)


if __name__ == "__main__":
    main()
