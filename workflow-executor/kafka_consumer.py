from confluent_kafka import Consumer, KafkaException, KafkaError
from typing import Dict, Callable
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KafkaMessageConsumer:
    def __init__(self, config: Dict):
        """
        config должен содержать параметры подключения к Kafka:
        {
            'bootstrap.servers': 'localhost:9092',
            'group.id': 'orchestrator_group',
            'auto.offset.reset': 'earliest'
        }
        """
        self.consumer = Consumer(config)
        self.is_running = False

    def subscribe(self, topics: list):
        """Подписка на топики"""
        self.consumer.subscribe(topics)
        logger.info(f"Подписались на топики: {topics}")

    def start_consuming(self, message_handler: Callable):
        """Запуск получения сообщений"""
        self.is_running = True
        try:
            while self.is_running:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.info("Достигнут конец партиции")
                    else:
                        logger.error(f"Ошибка: {msg.error()}")
                else:
                    try:
                        # Декодируем сообщение из JSON
                        value = json.loads(msg.value().decode("utf-8"))
                        # Обрабатываем сообщение
                        message_handler(value)
                    except json.JSONDecodeError as e:
                        logger.error(f"Ошибка декодирования JSON: {e}")
                    except Exception as e:
                        logger.error(f"Ошибка обработки сообщения: {e}")

        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки")
        finally:
            self.stop()

    def stop(self):
        """Остановка получения сообщений"""
        self.is_running = False
        self.consumer.close()
        logger.info("Консьюмер остановлен")
