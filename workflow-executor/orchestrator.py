import os
from typing import Dict, List, Optional
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor
from langchain.schema import SystemMessage
from langchain.prompts import MessagesPlaceholder
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents.format_scratchpad.openai_tools import format_to_openai_tool_messages
from langchain.agents.output_parsers.openai_tools import OpenAIToolsAgentOutputParser
from tools.agent_tools import get_tools
from kafka_consumer import KafkaMessageConsumer
from db.models import DatabaseManager
import json
import logging
from threading import Thread
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, kafka_config: Dict, db_url: str):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini", temperature=0.0, api_key=os.getenv("OPENAI_API_KEY")
        )
        self.tools = get_tools()
        self.context = {}

        # Инициализация Kafka консьюмера
        self.kafka_consumer = KafkaMessageConsumer(kafka_config)
        self.kafka_thread = None

        # Инициализация менеджера БД
        self.db_manager = DatabaseManager(db_url)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
            Ты - оркестратор мультиагентной системы. Твоя задача - координировать работу других агентов
            для выполнения бизнес-задачи. Ты должен:
            1. Анализировать текущий контекст задачи
            2. Определять, какой следующий шаг нужно выполнить
            3. Выбирать подходящего агента для выполнения подзадачи
            4. Обновлять контекст на основе результатов работы агентов
            5. Оценивать, выполнена ли общая задача

            Используй следующий формат:
            Задача: описание текущей бизнес-задачи
            Контекст: текущий контекст выполнения
            Мысль: анализ ситуации и принятие решения
            Действие: выбор действия (получение списка агентов/выполнение подзадачи/оценка выполнения)
            Входные данные: параметры для выбранного действия
            Наблюдение: результат действия
            ... (этот процесс может повторяться)
            Финальный ответ: решение о дальнейших действиях или завершении задачи
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

        self.agent_executor = AgentExecutor(agent=agent, tools=self.tools, verbose=True)

    def handle_kafka_message(self, message: Dict):
        """Обработка сообщения из Kafka"""
        logger.info(f"Получено сообщение: {message}")

        # Извлекаем необходимые поля из сообщения
        task_description = message.get("task_description")
        required_fields = message.get("required_fields", [])
        event_data = message.get("event_data", {})
        task_id = message.get("task_id", str(uuid.uuid4()))

        # Загружаем существующий контекст из БД
        self.context = self.db_manager.get_context(task_id)

        # Обновляем контекст данными события
        if event_data:
            self.update_context(task_id, event_data)

        # Если есть описание задачи, обрабатываем её
        if task_description:
            result = self.process_task(task_id, task_description, required_fields)
            logger.info(f"Результат обработки задачи: {result}")

    def update_context(self, task_id: str, new_context: Dict) -> None:
        """Обновляет контекст задачи новыми данными"""
        self.context.update(new_context)
        self.db_manager.save_context(task_id, self.context)
        logger.info(f"Контекст обновлен: {self.context}")

    def process_task(self, task_id: str, task_description: str, required_fields: List[str]) -> Dict:
        """Обрабатывает бизнес-задачу"""
        self.context["required_fields"] = required_fields

        response = self.agent_executor.invoke(
            {
                "input": f"""
                Бизнес-задача: {task_description}
                Текущий контекст: {self.context}
                
                Необходимо:
                1. Проанализировать текущий контекст
                2. Определить следующий шаг
                3. При необходимости делегировать подзадачу подходящему агенту
                4. Оценить выполнение общей задачи
                """
            }
        )

        # Сохраняем обновленный контекст в БД
        self.db_manager.save_context(task_id, self.context)

        return {"result": response["output"], "context": self.context}

    def start_kafka_consumer(self, topics: List[str]):
        """Запуск получения сообщений из Kafka в отдельном потоке"""
        self.kafka_consumer.subscribe(topics)
        self.kafka_thread = Thread(
            target=self.kafka_consumer.start_consuming,
            args=(self.handle_kafka_message,),
            daemon=True,
        )
        self.kafka_thread.start()
        logger.info(f"Начато получение сообщений из топиков: {topics}")

    def stop_kafka_consumer(self):
        """Остановка получения сообщений из Kafka"""
        if self.kafka_consumer:
            self.kafka_consumer.stop()
            if self.kafka_thread:
                self.kafka_thread.join()
                logger.info("Получение сообщений из Kafka остановлено")
