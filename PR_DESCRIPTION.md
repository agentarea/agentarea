# PR: Agent-to-Agent Communication (A2A) & Task Graph Support

## ✨  What’s new  
| Area | Summary |
|------|---------|
| **Core** | `AgentCommunicationService` orchestrates A2A requests, creates tasks for helper agents, tracks completion via events. |
| **Tools** | Google ADK compliant `AgentCommunicationTool` (`ask_agent`) auto-injected into LlmAgents so they can delegate work. |
| **Task Manager** | `BaseTaskManager` + `InMemoryTaskManager` extended with `on_get_tasks_by_user/agent`, metadata filtering and pending-task APIs. |
| **API** | New REST & JSON-RPC endpoints (`/v1/tasks/...`) for creating tasks, querying by user/agent, assigning, and starting execution. |
| **DI / Startup** | Registers `InMemoryTaskManager`, `AgentCommunicationService`, and wires them into runner & execution services. |
| **Docs & Examples** | `docs/agent_to_agent_communication.md`, `docs/task_assignment.md`, plus runnable Python demos in `examples/`. |

## ️🎯 Motivation
* Enable **declarative agent graphs** – agents can discover and call other agents as first-class capabilities.
* Provide a **simple delegation path** without over-engineering (tool-style synchronous call OR asynchronous sub-task).
* Lay groundwork for future marketplace / capability registry by standardising metadata and discovery patterns.

## 🔨  Implementation details

### 1.  AgentCommunication Layer
* `AgentCommunicationService`
  * `create_task_for_agent()` – creates A2A task, records completion `asyncio.Event`.
  * `wait_for_task_completion()` – resolves on `TaskCompleted`/`TaskFailed` events (timeout configurable).
  * Event subscriptions hooked up in `startup.py`.
* `AgentCommunicationTool`
  * ADK `Tool` spec `ask_agent`.
  * Accepts `agent_id`, `message`, `wait_for_response`, `metadata`.
  * Returns `task_id`, `status`, optional `response`.

### 2.  Runner Integration  
`AgentRunnerService` calls `AgentCommunicationService.configure_agent_with_communication()` which conditionally appends the tool to the agent’s tool list.

### 3.  Task & API Enhancements  
* `TaskManager` interface extended – fetch by **user_id** or **agent_id**.  
* `TaskService` & new FastAPI routes (`/tasks/...`) cover:
  * create / assign
  * start execution
  * list by user / agent
  * pending queue
* Simple authentication stub in `api/deps/auth.py`.

### 4.  DI & Startup  
`startup.register_services()` instantiates:
* `InMemoryTaskManager`
* `AgentCommunicationService` (requires existing `EventBroker`)
These are registered as singletons for injection.

### 5.  Docs & Examples  
* **Guide** – `docs/agent_to_agent_communication.md`
* **Task assignment guide** – `docs/task_assignment.md`
* **Runnable demo** – `examples/agent_to_agent_example.py`
* **REST demo** – `examples/task_assignment_examples.py`

## 🧪  How to test

```bash
# 1. start backend
uvicorn core.agentarea.main:app --reload

# 2. create two agents via REST (see docs)
# POST /v1/agents/

# 3. run example
python examples/agent_to_agent_example.py
```

Expected:
* Primary agent delegates to helper.
* Helper completes task, `AgentCommunicationService` unblocks, primary returns combined answer.
* Console prints velocity calculation with mocked LLM response.

## ➕  Future work / Out-of-scope
* Persistent TaskRepository (SQLAlchemy) – current impl is in-memory.
* Agent registry & discovery micro-service.
* Depth / cycle protection for recursive delegation.
* Robust auth & RBAC for agent access.

## ✅  Checklist
- [x] Unit tests pass (`pytest`)
- [x] New FastAPI endpoints documented via OpenAPI
- [x] Docs & examples added
- [x] No breaking changes to existing public APIs
- [x] Local manual test with mock LLM completes successfully

---
Let’s merge and start building the **Agent Graph**! 🚀
