# MCP Integration Tests

Этот модуль содержит интеграционные тесты для проверки работы AgentArea с реальными MCP серверами.

## Что тестируется

✅ **Создание агента** - Агенты создаются через API  
✅ **Развертывание MCP сервера** - С использованием Dockerfile  
✅ **Создание MCP Instance** - С конфигурацией окружения  
✅ **Выполнение задач** - С использованием MCP инструментов  
✅ **Проверка интеграции** - Все компоненты работают вместе  

## Запуск тестов

### 1. С помощью pytest

```bash
# Запуск всех MCP тестов
pytest tests/integration/test_mcp_real_integration.py -v

# Запуск конкретного теста
pytest tests/integration/test_mcp_real_integration.py::test_weather_mcp_integration -v
```

### 2. С помощью runner script

```bash
# Preset тесты
python scripts/run_mcp_tests.py --preset weather
python scripts/run_mcp_tests.py --preset filesystem

# Кастомный тест
python scripts/run_mcp_tests.py \
  --image weather-mcp:latest \
  --url http://weather-service:3000 \
  --tools examples/weather_mcp/tools.json \
  --name weather-mcp
```

### 3. Прямой запуск

```bash
cd tests/integration
python test_mcp_real_integration.py
```

## Структура тестов

### test_weather_mcp_integration()
Тестирует интеграцию с weather MCP сервером:
- Использует Python-based Dockerfile
- Инструменты: `get_weather`, `get_forecast`
- Тестовая задача: получение погоды в Москве

### test_filesystem_mcp_integration()
Тестирует интеграцию с filesystem MCP сервером:
- Использует FastAPI + uvicorn
- Инструменты: `read_file`, `write_file`, `list_directory`
- Тестовая задача: создание и чтение файла

### Custom MCP Integration (scripts/run_mcp_tests.py)
Настраиваемый тест для любого MCP сервера:
- Использует готовые Docker образы
- Прямые API вызовы (не зависит от тестовых классов)
- Полностью независимый workflow
- Кастомные инструменты через JSON файл

## Создание кастомного теста

### 1. Подготовьте файлы

**Docker Image** - соберите или получите готовый образ:
```bash
# Например, если у вас есть образ
docker pull myorg/custom-mcp:latest

# Или соберите свой
docker build -t my-custom-mcp:latest .
```

**Tools metadata** (например, `my_mcp/tools.json`):
```json
[
  {
    "name": "my_tool",
    "description": "Description of my tool",
    "parameters": {
      "type": "object",
      "properties": {
        "input": {"type": "string", "description": "Input parameter"}
      },
      "required": ["input"]
    }
  }
]
```

### 2. Запустите тест

```bash
python scripts/run_mcp_tests.py \
  --image my-custom-mcp:latest \
  --url http://my-mcp-service:3000 \
  --tools my_mcp/tools.json \
  --name my-mcp-server
```

## Требования

- AgentArea запущен на `http://localhost:8000`
- MCP Manager доступен и настроен
- Docker/Podman для развертывания MCP серверов
- Python пакеты: `pytest`, `httpx`, `asyncio`

## Архитектура тестирования

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Test Runner   │    │   AgentArea API  │    │  MCP Manager    │
│                 │────│                  │────│                 │
│ - pytest       │    │ - Agent CRUD     │    │ - Server Deploy │
│ - async/await   │    │ - Task Creation  │    │ - Instance Mgmt │
│ - httpx client  │    │ - MCP Integration│    │ - Container Ops │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   Real MCP       │
                       │   Server         │
                       │                  │
                       │ - Docker Container│
                       │ - MCP Protocol    │
                       │ - Custom Tools    │
                       └──────────────────┘
```

## Troubleshooting

**Тест не проходит:**
1. Проверьте что AgentArea запущен: `curl http://localhost:8000/v1/agents/`
2. Проверьте логи MCP Manager: `docker logs mcp-manager`
3. Убедитесь что Docker доступен для MCP Manager

**Ошибки создания задач:**
1. Проверьте что агент создался корректно
2. Убедитесь что MCP instance в статусе "running"
3. Проверьте connectivity между сервисами

**Проблемы с Dockerfile:**
1. Убедитесь что Dockerfile валидный
2. Проверьте что порт 3000 используется в команде CMD
3. Убедитесь что все зависимости указаны

## Примеры

В директории `examples/` есть готовые примеры MCP серверов для тестирования:

- `examples/weather_mcp/` - Weather service
- `examples/filesystem_mcp/` - File operations (создать при необходимости)
- `examples/database_mcp/` - Database operations (создать при необходимости)

Используйте их как шаблоны для своих MCP серверов! 