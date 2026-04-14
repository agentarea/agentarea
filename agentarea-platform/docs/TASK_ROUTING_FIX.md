# Fix: Unified Task Creation & Follow-Up Routing

## Problem

1. **Task creation scattered across 7+ places** — каждый path (API, triggers, A2A, delegation) создаёт задачи по-своему. Routing follow-up messages пришлось патчить в каждом месте отдельно — fragile, дублирование, ошибки.

2. **Каждое сообщение = новая задача** — когда пользователь отправляет несколько сообщений подряд в канал (Telegram, Slack), каждое создаёт отдельный workflow без контекста предыдущих.

3. **Follow-up routing работает только частично** — добавлен в `trigger_execution_activities.py` и `trigger_service.py`, но Go poller path идёт через `inbound_subscriber.py` → `trigger_service.execute_trigger()`, где routing может не сработать из-за отсутствия `workflow_executor`.

## Current Architecture (broken)

```
Telegram → Go Poller → Redis pub/sub → InboundMessageSubscriber
                                              ↓
                                     trigger_service.execute_trigger()
                                              ↓
                                     ALWAYS creates new task  ← BUG
                                              ↓
                                     TemporalTaskManager.submit_task()
                                              ↓
                                     AgentExecutionWorkflow (new)
```

## Root Cause

`InboundMessageSubscriber._handle_message()` (строка 108-137) получает inbound message и **всегда** вызывает `_execute_trigger()` → `trigger_service.execute_trigger()` → creates new task. Нет проверки "есть ли уже active workflow для этого channel + agent".

## Fix: Route Before Execute

### Where to add routing

**Единственное правильное место: `InboundMessageSubscriber._handle_message()`** (строка 108)

Это единая точка входа для ВСЕХ inbound channel messages (Go poller → Redis → subscriber). Routing здесь покрывает все каналы без дублирования.

### Logic

```python
async def _handle_message(self, raw_message):
    msg = json.loads(payload)
    trigger_id = msg["trigger_id"]
    event = msg.get("event", {})
    channel_origin = msg.get("channel_origin", {})
    message_text = event.get("text", "")
    
    # 1. Try to route to existing active workflow
    if message_text and channel_origin.get("chat_id") and self._workflow_executor:
        routed = await self._try_route_to_active_workflow(
            trigger_id, channel_origin, message_text
        )
        if routed:
            return  # Message delivered to existing workflow, done
    
    # 2. No active workflow — create new task via trigger
    trigger_data = {"events": [event], "channel_origin": channel_origin}
    await self._execute_trigger(trigger_id, trigger_data)
```

### Helper method

```python
async def _try_route_to_active_workflow(
    self, trigger_id: str, channel_origin: dict, message_text: str
) -> bool:
    """Find active workflow for this channel and route message to it."""
    from uuid import UUID
    from sqlalchemy import select
    from agentarea_common.config import get_database
    from agentarea_tasks.infrastructure.orm import TaskORM
    from agentarea_triggers.infrastructure.orm import TriggerORM

    chat_id = str(channel_origin.get("chat_id", ""))
    if not chat_id:
        return False

    database = get_database()
    async with database.async_session_factory() as session:
        # Get trigger to know agent_id and workspace_id
        trigger = await session.get(TriggerORM, UUID(trigger_id))
        if not trigger:
            return False

        # Find most recent running/completed task for same agent + chat_id
        result = await session.execute(
            select(TaskORM)
            .where(
                TaskORM.agent_id == trigger.agent_id,
                TaskORM.workspace_id == str(trigger.workspace_id),
                TaskORM.status.in_(["running", "completed"]),
            )
            .order_by(TaskORM.created_at.desc())
            .limit(5)
        )
        
        for task in result.scalars().all():
            params = task.parameters or {}
            task_chat_id = str(params.get("channel_origin", {}).get("chat_id", ""))
            if task_chat_id == chat_id and task.execution_id:
                ok = await self._workflow_executor.send_workflow_command(
                    task.execution_id,
                    "queue_message",
                    {"message": message_text},
                )
                if ok:
                    logger.info(
                        "Routed follow-up to workflow %s (chat_id=%s)",
                        task.execution_id, chat_id,
                    )
                    return True
    return False
```

### What to remove

После добавления routing в `InboundMessageSubscriber`, **удалить** дублирующий routing из:
1. `trigger_execution_activities.py` (строки 262-311) — routing block перед task creation
2. `trigger_service.py` (строки 1030-1065) — routing block перед task creation

Эти были temporary patches. Единственный routing point = InboundMessageSubscriber.

### Files to modify

| File | Action |
|------|--------|
| `libs/triggers/agentarea_triggers/channels/inbound_subscriber.py` | Add `_try_route_to_active_workflow()`, modify `_handle_message()` |
| `libs/execution/agentarea_execution/activities/trigger_execution_activities.py` | Remove routing block (lines 262-311), restore original simple task creation |
| `libs/triggers/agentarea_triggers/trigger_service.py` | Remove routing block (lines 1030-1065), restore original task creation |

### Query format

Workflow `_handle_queue_message` принимает:
```python
payload.get("message") or payload.get("content")  # Both accepted
```

Всегда отправлять `{"message": text}` для consistency.

## Phase 2 (не сейчас)

1. **Session model** — `sessions` table в PostgreSQL, session_id FK на tasks
2. **Session context injection** — при создании новой задачи подгружать summary предыдущей сессии в system prompt
3. **Configurable timeout** — per-agent/per-trigger follow-up timeout вместо hardcoded 30 min
4. **Typed command models** — Pydantic models для workflow commands вместо raw dicts
5. **Unified task creation** — все 7 paths должны использовать один метод `TaskService.create_or_route_task()` с routing logic внутри

## Testing

1. **Unit test**: `_try_route_to_active_workflow` returns True when active workflow found
2. **Unit test**: Returns False when no active workflow
3. **Unit test**: Returns False when signal fails (workflow dead)
4. **Unit test**: Different chat_ids don't cross-route
5. **Integration test**: Send 2 messages via API → second goes to same workflow
6. **Manual test**: Telegram — send 3 messages fast → all in one task, agent has full context

## Verification commands

```bash
# After fix, send "привет" via Telegram, then "что умеешь?"
# Check tasks list:
curl -s http://localhost:8000/v1/tasks/ -H "Authorization: Bearer TOKEN" | python3 -c "
import sys, json
tasks = json.load(sys.stdin)
for t in tasks[:5]:
    print(f'{t[\"id\"][:8]} | {t[\"status\"]} | {t[\"description\"][:30]}')
"
# Should see ONE task, not two
```
