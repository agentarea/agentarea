# Расширяемая архитектура событийной системы AgentArea

## Обзор архитектуры

Новая архитектура событийной системы построена на принципах расширяемости, гибкости и масштабируемости.

### Ключевые компоненты:

1. **Event Source Registry** - Реестр источников событий
2. **Event Schema Registry** - Реестр схем событий с версионированием
3. **Advanced Filter Engine** - Продвинутая система фильтрации
4. **Task Template System** - Шаблонная система создания задач
5. **Advanced Event Processor** - Обработчик событий нового поколения

## Примеры конфигураций

### Подписка на Telegram сообщения
```json
{
  "name": "Telegram Support Bot",
  "event_type": "telegram_message",
  "event_filters": {
    "filters": [
      {
        "type": "field",
        "field_path": "chat_id",
        "operator": "in",
        "value": ["support_chat_1", "support_chat_2"]
      },
      {
        "type": "field",
        "field_path": "message",
        "operator": "contains",
        "value": "help"
      }
    ]
  },
  "task_template_id": "telegram_response",
  "priority": 1
}
```

### Составные фильтры
```json
{
  "event_filters": {
    "filters": [
      {
        "type": "composite",
        "operator": "OR",
        "filters": [
          {
            "type": "field",
            "field_path": "priority",
            "operator": "eq",
            "value": "high"
          },
          {
            "type": "field",
            "field_path": "amount",
            "operator": "gt",
            "value": 1000
          }
        ]
      }
    ]
  }
}
```

### Условный шаблон задачи
```json
{
  "template_id": "conditional_task",
  "description_template": "Process {event.type} for {event.user_id}",
  "parameters_template": {
    "user_id": "{event.user_id}",
    "priority": "{ 0f event.amount > 1000 