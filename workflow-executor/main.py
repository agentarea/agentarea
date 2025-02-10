import logging
from orchestrator import Orchestrator
from config import get_kafka_config, get_db_config, get_kafka_topics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    # Получаем конфигурацию из переменных окружения
    kafka_config = get_kafka_config()
    db_url = get_db_config()
    kafka_topics = get_kafka_topics()

    # Создаем экземпляр оркестратора
    orchestrator = Orchestrator(kafka_config, db_url)

    try:
        # Запускаем получение сообщений из нужных топиков
        orchestrator.start_kafka_consumer(kafka_topics)

        # Держим приложение запущенным
        input("Нажмите Enter для завершения...\n")

    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения работы")
    finally:
        orchestrator.stop_kafka_consumer()


if __name__ == "__main__":
    main()
