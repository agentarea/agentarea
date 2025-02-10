import requests
import yaml
from typing import Dict, List, Optional
import json
import os
from langchain_openai import ChatOpenAI
from langchain.agents import create_react_agent, AgentExecutor
from langchain.schema import SystemMessage
from langchain.prompts import MessagesPlaceholder, PromptTemplate
from langchain.memory import ConversationBufferMemory
from tools.agent_tools import get_tools
from langchain.agents.format_scratchpad.openai_tools import (
    format_to_openai_tool_messages,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents.output_parsers.openai_tools import OpenAIToolsAgentOutputParser


class AgentConstructor:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini", temperature=0.0, api_key=os.getenv("OPENAI_API_KEY")
        )
        self.tools = get_tools()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
                        Ты - эксперт по построению мультиагентных систем.
                        Твоя задача - создавать YAML-конфигурации систем на основе описания задачи.

                        Используй следующий формат:
                        Вопрос: входной вопрос, на который нужно ответить
                        Мысль: ты всегда должен думать о том, что делать
                        Действие: действие, которое нужно предпринять
                        Входные данные действия: входные данные для действия
                        Наблюдение: результат действия. Покажи результат действия в виде текста.
                        ... (этот процесс Мысль/Действие/Входные данные действия/Наблюдение может повторяться N раз)
                        Мысль: Теперь я знаю окончательный ответ
                        Финальный ответ: окончательный ответ на входной вопрос

                """,
                ),
                ("user", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        llm_with_tools = self.llm.bind_tools(self.tools)

        agent = (
            {
                "input": lambda x: x["input"],
                "agent_scratchpad": lambda x: format_to_openai_tool_messages(
                    x["intermediate_steps"]
                ),
            }
            | prompt
            | llm_with_tools
            | OpenAIToolsAgentOutputParser()
        )

        self.agent = AgentExecutor(agent=agent, tools=self.tools, verbose=True)

    def construct_system(self, task_description: str) -> str:
        """Конструирует мультиагентную систему на основе описания задачи"""
        response = self.agent.invoke(
            {
                "input": f"""
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

        return response["output"]


def main():
    constructor = AgentConstructor()
    task = """Перечисли какие агенты тебе доступны?"""
    system_yaml = constructor.construct_system(task)
    print(system_yaml)


if __name__ == "__main__":
    main()
