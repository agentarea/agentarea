# AgentArea Test Suite
Правильно организованная тестовая инфраструктура с разделением на unit и integration тесты.

## 📁 Структура тестов

```
tests/
├── unit/                        # ✅ Unit тесты (изолированные, с моками)
│   └── test_basic.py               # ✅ Базовые математические операции (2 теста)
├── integration/                 # ✅ Integration тесты (реальные сервисы)  
│   ├── test_integration_simple.py # ✅ Простая Ollama интеграция (работает!)
│   ├── test_integration_ollama.py # 🔧 Продвинутые интеграционные тесты
│   └── test_presigned_url.py      # 🔧 AWS интеграция (требует настройки)
├── conftest.py                  # ✅ Глобальные фикстуры pytest
└── README.md                    # Этот файл
```

## 🧪 Типы тестов

### ✅ Unit Tests (`tests/unit/`)
- **Цель**: Тестируют отдельные компоненты изолированно
- **Характеристики**: Быстрые, используют моки, без внешних зависимостей
- **Статус**: 2 теста работают
- **Команда**: `pytest tests/unit/ -v`

### ✅ Integration Tests (`tests/integration/`)
- **Цель**: Тестируют полную интеграцию системы с реальными сервисами
- **Требования**: База данных, Ollama, реальные LLM вызовы
- **Статус**: Система работает, есть проблема с парсингом ответов
- **Команда**: `PYTHONPATH=/Users/jamakase/Projects/startup/agentarea/core python tests/integration/test_integration_simple.py`

## 🚀 Быстрый старт

### 1. Unit тесты (быстро, не требуют настройки)
```bash
# Запуск unit тестов
pytest tests/unit/ -v

# Результат: 
# tests/unit/test_basic.py::test_addition PASSED
# tests/unit/test_basic.py::test_multiplication PASSED  
# ============ 2 passed in 0.01s =============
```

### 2. Integration тесты (требуют настройки)
```bash
# Подготовка (если еще не сделано)
docker-compose -f docker-compose.local.yaml --env-file .env.local up db -d
python -m cli migrate
python setup_ollama_data.py
ollama pull qwen2.5

# Запуск интеграционного теста
PYTHONPATH=/Users/jamakase/Projects/startup/agentarea/core python tests/integration/test_integration_simple.py

# Результат: ✅ Ollama отвечает, но есть проблема с парсингом Response
```

## 📊 Статус тестов

### ✅ Работающие тесты
- **Unit tests**: `test_basic.py` - базовые математические операции
- **Integration**: Ollama успешно отвечает на запросы через OpenAI-совместимый транспорт

### 🔧 Нужно исправить
- **Integration response parsing**: Ответы получаются, но парсятся как пустые
- **AWS тесты**: Требуют настройки AWS credentials

### 🎯 Результаты интеграционных тестов
```
✅ Модель найдена: "Local Qwen2.5"  
✅ LLM подключается к Ollama (localhost:11434)
✅ Получены валидные ответы:
   - Математика: "12" (на 7+5)
   - Русский: "Привет! Меня зовут integration_test_agent..."
   - Творческое: "AI and programming are intertwined..."

❌ Проблема: Response парсится как пустой, хотя raw response содержит данные
```

## 🔧 Команды для разработки

```bash
# Все unit тесты
pytest tests/unit/ -v

# Все тесты с маркерами  
pytest -m unit          # Только unit тесты
pytest -m integration   # Только integration тесты

# Конкретный тест
pytest tests/unit/test_basic.py::test_addition -v

# С покрытием (когда будет больше тестов)
pytest --cov=agentarea tests/unit/ 

# Самые медленные тесты
pytest --durations=10
```

## 📈 Дальнейшее развитие

### Unit тесты
- Добавить тесты для утилитарных функций
- Тесты конфигурационных объектов  
- Тесты валидации данных

### Integration тесты
- Исправить парсинг ответов в `test_integration_simple.py`
- Добавить тесты для MCP серверов
- Тесты для разных LLM провайдеров

## 🎉 Резюме

**Успешно создана структура тестов:**
- ✅ Unit тесты работают (2/2 passed)
- ✅ Integration тесты подключаются к Ollama  
- ✅ Модели вызываются через собственные транспорты SDK (OpenAI-совместимый и Anthropic)
- ✅ Система готова для расширения тестов

**Следующий шаг:** Исправить парсинг ответов в интеграционных тестах. 