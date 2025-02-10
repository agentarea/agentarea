import os
from typing import Dict
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


def get_kafka_config() -> Dict:
    """Получает конфигурацию для Kafka из переменных окружения"""
    return {
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        "group.id": os.getenv("KAFKA_GROUP_ID", "orchestrator_group"),
        "auto.offset.reset": os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"),
        "security.protocol": os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
        "sasl.mechanism": os.getenv("KAFKA_SASL_MECHANISM", "PLAIN"),
        "sasl.username": os.getenv("KAFKA_USERNAME", ""),
        "sasl.password": os.getenv("KAFKA_PASSWORD", ""),
    }


def get_db_config() -> str:
    """Получает конфигурацию для базы данных из переменных окружения"""
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "orchestrator")
    db_user = os.getenv("DB_USER", "user")
    db_password = os.getenv("DB_PASSWORD", "password")

    return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


def get_llm_config() -> Dict:
    """Получает конфигурацию для LLM из переменных окружения"""
    return {
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.0")),
        "api_key": os.getenv("OPENAI_API_KEY"),
    }


def get_kafka_topics() -> list:
    """Получает список топиков Kafka из переменных окружения"""
    topics_str = os.getenv("KAFKA_TOPICS", "tasks,events")
    return topics_str.split(",")
