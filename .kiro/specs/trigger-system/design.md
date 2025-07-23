# Trigger System Design Document

## Overview

The trigger system enables automated agent execution based on two primary trigger types: cron-based scheduled triggers and webhook-based event triggers. The system integrates with the existing AgentArea architecture, leveraging the current TaskService, EventBroker, and agent execution infrastructure to provide a reactive automation layer that allows agents to run on schedules or react to external events without manual intervention.

**Key Design Decisions:**

- **Interface-driven architecture**: All major components (TriggerScheduler, WebhookManager, ConditionEvaluator) are defined as interfaces, allowing different implementations to be plugged in without changing the core TriggerService logic (supports Requirements 1.1, 1.2)
- **Dependency inversion**: TriggerService depends on abstractions, not concrete implementations, following SOLID principles and enabling testability and flexibility
- **Pluggable scheduling backends**: TriggerScheduler interface allows for different scheduling implementations (Temporal, APScheduler, Celery, etc.) to be used based on deployment requirements (supports Requirement 5.1-5.5)
- **Event-driven architecture**: Triggers evaluate events and create agent tasks rather than directly executing agents, maintaining separation of concerns and leveraging existing TaskService infrastructure (supports Requirements 2.1-2.3)
- **Independent trigger execution**: Multiple triggers can match the same event and execute independently, ensuring parallel automation workflows without interference (supports Requirement 2.4)
- **Pluggable webhook processing**: WebhookManager interface with pluggable parsers for different webhook types (Telegram, Slack, GitHub) enables extensible webhook support (supports Requirements 6.1-6.5, 7.1-7.5)
- **Configurable condition evaluation**: ConditionEvaluator interface allows for different rule engines and evaluation strategies to be implemented (supports Requirements 8.1, 8.2, 8.5)
- **Unified trigger interface**: Both cron and webhook triggers share common lifecycle management and execution patterns for consistent behavior and administration (supports Requirements 3.1-3.4)
- **Comprehensive monitoring**: Detailed execution history and logging for troubleshooting and workflow understanding, including task correlation and error tracking (Requirements 4.1-4.4)
- **Rate limiting and safety**: Built-in protection against excessive executions and system abuse through configurable rate limits and failure thresholds (Requirements 9.1-9.5)
- **Lifecycle management**: Complete trigger lifecycle control including enable/disable/delete operations for operational flexibility (Requirements 3.1-3.4)
- **Validation and error handling**: Comprehensive validation of trigger configurations, agent existence, and graceful error handling with detailed logging (Requirements 1.2, 1.4, 5.5)
- **Predefined webhook integrations**: Support for common services like Telegram, Slack, and GitHub with automatic parsing and validation (Requirements 7.1-7.5)
- **Task metadata tracking**: All tasks created by triggers include trigger metadata for tracking and debugging purposes (Requirements 9.4)

## Architecture

### High-Level Architecture

```
┌─────────────────┐    ┌─────────────────┐
│  Webhook Server │    │  HTTP Handlers  │
│                 │    │                 │
│ - FastAPI       │    │ - Route Mapping │
│ - HTTP Endpoints│    │ - Request Parse │
│ - Response Gen  │    │ - Validation    │
└─────────────────┘    └─────────────────┘
         │                       │
         └───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │ Trigger Service │
                    │                 │
                    │ - CRUD Ops      │
                    │ - Event Match   │
                    │ - Condition Eval│
                    │ - Task Creation │
                    └─────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                       │                        │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Scheduler       │    │ Webhook Manager │    │   Task Service  │
│ Interface       │    │ Interface       │    │                 │
│                 │    │                 │    │ - Create Tasks  │
│ - Cron Timing   │    │ - Generate URLs │    │ - Execute Tasks │
│ - Callbacks     │    │ - Parse Requests│    │ - Agent Workflows│
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                                                  │
         │                                                  │
┌─────────────────┐                                         │
│ APScheduler     │                                         │
│ or Temporal     │                                         │
│ or Celery       │                                         │
│ (Just Timing)   │                                         │
│                 │                                         │
└─────────────────┘                                         │
                                                          │
                                            ┌─────────────────┐
                                            │ Temporal Worker │
                                            │                 │
                                            │ - Task Workflows│
                                            │ - Agent Exec    │
                                            │ - Retry/Durability│
                                            └─────────────────┘
```

### Trigger Validation and Error Handling

The system implements comprehensive validation at multiple levels to ensure trigger reliability and proper error handling:

**Trigger Creation Validation (Requirements 1.2, 1.4, 5.5):**

- **Agent Existence Validation**: Verify that the specified agent exists in the system before creating triggers
- **Event Type Validation**: Ensure that the event type is supported by the system
- **Cron Expression Validation**: Validate cron expression syntax and logical correctness
- **Webhook Configuration Validation**: Validate HTTP methods, URL patterns, and service-specific configurations
- **Condition Syntax Validation**: Validate trigger conditions and filters for proper syntax and semantics

**Runtime Error Handling (Requirements 2.5, 4.4):**

- **Execution Failure Logging**: Record detailed error information when trigger execution fails
- **Graceful Degradation**: Continue processing other triggers when individual triggers fail
- **Timeout Handling**: Implement configurable timeouts for trigger execution with proper cleanup
- **Service Unavailability**: Handle cases where external services (LLM, TaskService) are temporarily unavailable

**Error Recovery and Safety (Requirements 9.3, 9.5):**

- **Automatic Trigger Disabling**: Disable triggers after consecutive failures exceed threshold
- **Circuit Breaker Pattern**: Prevent cascading failures by temporarily stopping trigger evaluation
- **Error Correlation**: Link trigger execution errors with created tasks for debugging

### Component Integration

The trigger system integrates with existing AgentArea components through well-defined interfaces:

- **TriggerScheduler Interface**: Abstracts scheduling implementation (APScheduler, Temporal, Celery) - **only handles timing**
- **TaskService**: Creates and executes agent tasks when triggers fire - **handles all execution logic**
- **EventBroker**: Publishes trigger execution events for monitoring
- **Agent Repository**: Validates agent existence before trigger creation
- **Database**: Stores trigger configurations and execution history
- **WebhookManager Interface**: Abstracts webhook handling and parsing logic

**Component Explanations**:

- **Webhook Server**: FastAPI endpoints that receive HTTP requests from external services
- **HTTP Handlers**: Route mapping and request processing logic
- **Trigger Service**:
  - **CRUD Ops**: Create, read, update, delete triggers
  - **Event Match**: Find triggers that match incoming events
  - **LLM Condition Eval**: Use LLM to evaluate natural language conditions like "when user sends a file" or "if this looks like a sales inquiry"
  - **Task Creation**: Call TaskService to create tasks when conditions are met
- **Scheduler Interface**: Just handles timing - when to fire cron triggers via callbacks
- **Webhook Manager**:
  - **Generate URLs**: Creates unique webhook URLs like `/webhooks/abc123` for each trigger
  - **Raw Data Processing**: Just extracts raw JSON/form data, no specific parsing
- **Task Service**: Creates and executes agent tasks (the actual work)

**Key Architectural Principle**:

- **Separation of Concerns**: Scheduler handles **when** (timing), TaskService handles **what** (execution)
- **Interface-Driven**: TriggerService depends only on interfaces, not concrete implementations
- **Task-Centric**: Everything is a task - webhook responses, scheduled actions, multi-step agent workflows

### Event Processing Flow

The system follows a clean separation between timing and execution, with comprehensive event evaluation and execution tracking:

#### Cron Trigger Flow (Requirements 5.1-5.5)

1. **Scheduler fires** at the scheduled time (APScheduler/Temporal/Celery)
2. **Callback to TriggerService** with trigger_id and timing data
3. **TriggerService loads trigger** and validates it's still active and agent exists
4. **Condition evaluation** - check if trigger conditions are met for current context
5. **If conditions match**, TriggerService calls TaskService to create a task with trigger metadata
6. **TaskService executes** the agent workflow (potentially using Temporal for durability)
7. **Execution recorded** with detailed metadata including timestamp, event data, and result status
8. **Error handling** - log failures and update consecutive failure count

#### Webhook Trigger Flow (Requirements 6.1-6.5, 7.1-7.5)

1. **HTTP request received** by WebhookManager at unique webhook URL
2. **Request validation** - check HTTP method, rate limits, and basic format
3. **Request parsed** by appropriate webhook parser (generic, Telegram, Slack, GitHub)
4. **TriggerService evaluates** all matching webhook triggers for the webhook_id
5. **Condition evaluation** - check trigger conditions against parsed request data
6. **Multiple trigger execution** - execute all matching triggers independently
7. **Task creation** - call TaskService to create tasks with trigger metadata and request data
8. **TaskService executes** the agent workflows
9. **HTTP response returned** to webhook caller with appropriate status
10. **Execution recorded** for all triggered executions with correlation to original request

#### Event Evaluation Process (Requirements 2.1-2.5)

The system implements a comprehensive event evaluation process:

1. **Event Reception**: System receives either scheduled event (cron) or external event (webhook)
2. **Active Trigger Discovery**: Find all active triggers that could match the event type
3. **Condition Evaluation**: For each potential trigger, evaluate conditions using:
   - Simple rule-based conditions for basic filtering
   - LLM-based natural language conditions for complex scenarios
4. **Independent Execution**: Execute all matching triggers independently and in parallel
5. **Error Isolation**: Ensure that failure of one trigger doesn't affect others
6. **Execution Tracking**: Record detailed execution history for monitoring and debugging

**Key Design Decision - Task-Centric Execution**: Everything becomes a task. Whether it's responding to a Telegram message with 5 actions, processing a GitHub webhook, or running a scheduled report - it all goes through TaskService as a unified execution model. This provides consistency, durability, and monitoring across all trigger types.

#### Example: Smart Telegram Bot

```python
# 1. User creates webhook trigger with natural language condition:
#    "When user sends a file, analyze it and respond with insights"
# 2. WebhookManager generates URL: https://api.example.com/webhooks/tg_abc123
# 3. User configures Telegram bot to send messages to that URL
# 4. When message arrives:
#    - FastAPI receives POST /webhooks/tg_abc123
#    - WebhookManager extracts raw Telegram JSON data
#    - TriggerService uses LLM to evaluate: "Does this message contain a file?"
#    - LLM analyzes the JSON and returns: "Yes, user sent a PDF document"
#    - TriggerService calls TaskService.create_task(
#        agent_id=trigger.agent_id,
#        task_type="file_analysis",
#        parameters={
#          "chat_id": telegram_data["chat_id"],
#          "file_url": telegram_data["document"]["file_id"],
#          "user_message": telegram_data["text"],
#          "instruction": "analyze it and respond with insights"
#        }
#      )
#    - TaskService executes the file analysis workflow
#    - WebhookManager returns HTTP 200 OK to Telegram

#### Example: Smart Email Routing
# Trigger condition: "If this looks like a sales inquiry, route to sales agent.
#                     If it's a support request, route to support agent."
# LLM evaluates email content and decides routing automatically
```

### Interface-Based Design Benefits

- **Flexibility**: Different scheduling backends can be used based on requirements (Temporal for complex workflows, APScheduler for simple cron jobs, etc.)
- **Testability**: Interfaces can be easily mocked for unit testing without requiring actual scheduling infrastructure
- **Maintainability**: Changes to scheduling implementation don't affect the core trigger logic
- **Extensibility**: New scheduling backends, webhook processors, or condition evaluators can be added without modifying existing code
- **Deployment Options**: Different environments can use different implementations (e.g., in-memory scheduler for testing, Temporal for production)

## Components and Interfaces

### 1. Trigger Domain Models

#### Trigger Base Model

```python
@dataclass
class Trigger:
    id: UUID
    name: str
    description: str
    agent_id: UUID
    trigger_type: TriggerType  # CRON, WEBHOOK
    is_active: bool
    task_parameters: dict[str, Any]
    conditions: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: str

    # Rate limiting and safety
    max_executions_per_hour: int = 60
    failure_threshold: int = 5
    consecutive_failures: int = 0
    last_execution_at: Optional[datetime] = None
```

#### Cron Trigger Model

```python
@dataclass
class CronTrigger(Trigger):
    cron_expression: str
    timezone: str = "UTC"
    next_run_time: Optional[datetime] = None
```

#### Webhook Trigger Model

```python
@dataclass
class WebhookTrigger(Trigger):
    webhook_id: str  # Unique identifier for webhook URL
    allowed_methods: list[str] = field(default_factory=lambda: ["POST"])
    webhook_type: WebhookType = WebhookType.GENERIC
    validation_rules: dict[str, Any] = field(default_factory=dict)

    # Generic webhook configuration - supports any webhook type
    webhook_config: dict[str, Any] = field(default_factory=dict)
```

#### Trigger Execution Record

```python
@dataclass
class TriggerExecution:
    id: UUID
    trigger_id: UUID
    executed_at: datetime
    status: ExecutionStatus  # SUCCESS, FAILED, TIMEOUT
    task_id: Optional[UUID] = None
    execution_time_ms: int
    error_message: Optional[str] = None
    trigger_data: dict[str, Any] = field(default_factory=dict)
    workflow_id: Optional[str] = None  # Temporal workflow ID
    run_id: Optional[str] = None       # Temporal run ID
```

#### Temporal Configuration Models

@dataclass
class CronTriggerConfig:
trigger_id: UUID
cron_expression: str
timezone: str
agent_id: UUID
task_parameters: dict[str, Any]
conditions: dict[str, Any]

    @classmethod
    def from_trigger(cls, trigger: CronTrigger) -> 'CronTriggerConfig':
        return cls(
            trigger_id=trigger.id,
            cron_expression=trigger.cron_expression,
            timezone=trigger.timezone,
            agent_id=trigger.agent_id,
            task_parameters=trigger.task_parameters,
            conditions=trigger.conditions
        )

@dataclass
class WebhookRequestData:
webhook_id: str
method: str
headers: dict[str, str]
body: Any
query_params: dict[str, str]
received_at: datetime

@dataclass
class WebhookValidationResult:
is_valid: bool
parsed_data: dict[str, Any]
error_message: Optional[str] = None

`````

### 2. Trigger Service

#### Core Service Implementation

```python
class TriggerService:
    """
    Core trigger service that orchestrates trigger lifecycle and execution.
    Depends only on interfaces, not concrete implementations.
    """

    def __init__(
        self,
        trigger_repository: TriggerRepository,
        task_service: TaskService,
        event_broker: EventBroker,
        agent_repository: AgentRepository,
        trigger_scheduler: TriggerScheduler,  # Interface, not implementation
        webhook_manager: WebhookManager,      # Interface, not implementation
        llm_service: LLMService,              # For condition evaluation
    ):
        self._trigger_repository = trigger_repository
        self._task_service = task_service
        self._event_broker = event_broker
        self._agent_repository = agent_repository
        self._trigger_scheduler = trigger_scheduler
        self._webhook_manager = webhook_manager
        self._llm_service = llm_service


    # CRUD Operations
    async def create_trigger(self, trigger: Trigger) -> Trigger
    async def get_trigger(self, trigger_id: UUID) -> Optional[Trigger]
    async def update_trigger(self, trigger: Trigger) -> Trigger
    async def delete_trigger(self, trigger_id: UUID) -> bool
    async def list_triggers(self, filters: dict) -> list[Trigger]

    # Lifecycle Management
    async def enable_trigger(self, trigger_id: UUID) -> bool
    async def disable_trigger(self, trigger_id: UUID) -> bool

    # Event Processing and Execution
    async def evaluate_all_triggers_for_event(self, event_data: dict, event_type: str) -> list[Trigger]
    async def execute_trigger(self, trigger: Trigger, trigger_data: dict) -> TriggerExecution
    async def execute_matching_triggers(self, event_data: dict, event_type: str) -> list[TriggerExecution]
    async def get_execution_history(self, trigger_id: UUID, filters: dict = None) -> list[TriggerExecution]
    async def evaluate_trigger_conditions(self, trigger: Trigger, event_data: dict) -> bool
    async def validate_condition_syntax(self, conditions: dict) -> list[str]

    # Task Creation (delegates to TaskService)
    async def create_task_from_trigger(self, trigger: Trigger, trigger_data: dict) -> UUID
    async def build_task_parameters(self, trigger: Trigger, trigger_data: dict) -> dict[str, Any]

    # Validation
    async def validate_trigger_configuration(self, trigger: Trigger) -> list[str]
    async def validate_agent_exists(self, agent_id: UUID) -> bool
    async def validate_cron_expression(self, cron_expression: str) -> bool
    async def validate_webhook_configuration(self, webhook_trigger: WebhookTrigger) -> list[str]
```

#### Condition Evaluation System

The trigger system implements a flexible condition evaluation system that supports both simple rule-based conditions and advanced LLM-based natural language conditions (Requirements 8.1, 8.2, 8.5):

**Simple Rule-Based Conditions:**
- JSON path-based field matching (e.g., `request.body.message_type == "file"`)
- HTTP header validation (e.g., `headers.content-type == "application/json"`)
- Query parameter filtering (e.g., `query.action == "deploy"`)
- Time-based conditions for cron triggers (e.g., `hour >= 9 AND hour <= 17`)

**LLM-Based Natural Language Conditions:**
- Natural language descriptions (e.g., "when user sends a file", "if this looks like a sales inquiry")
- Context-aware evaluation using event data and trigger history
- Semantic understanding of webhook payloads and user intent
- Dynamic parameter extraction from natural language conditions

**Condition Evaluation Process:**
1. **Syntax Validation**: Validate condition syntax during trigger creation
2. **Context Preparation**: Prepare event data and trigger context for evaluation
3. **Rule Engine**: Apply simple conditions using rule-based evaluation
4. **LLM Evaluation**: Use LLM service for natural language condition evaluation
5. **Result Combination**: Combine results from multiple condition types
6. **Logging**: Record condition evaluation results for debugging and monitoring

**Example Condition Configurations:**
```python
# Simple rule-based condition
simple_condition = {
    "type": "rule",
    "rules": [
        {"field": "request.method", "operator": "eq", "value": "POST"},
        {"field": "request.body.event_type", "operator": "eq", "value": "push"}
    ],
    "logic": "AND"
}

# LLM-based natural language condition
llm_condition = {
    "type": "llm",
    "description": "When user sends a file attachment or document",
    "context_fields": ["request.body", "request.headers"],
    "examples": [
        {"input": {"body": {"document": {"file_name": "report.pdf"}}}, "expected": True},
        {"input": {"body": {"text": "hello world"}}, "expected": False}
    ]
}

# Combined condition
combined_condition = {
    "type": "combined",
    "conditions": [simple_condition, llm_condition],
    "logic": "OR"
}
```

### 3. Trigger Scheduler Interface

#### Abstract Scheduler Interface

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable

class TriggerScheduler(ABC):
    """
    Abstract interface for trigger scheduling implementations.
    Responsible ONLY for timing - when to fire triggers.
    Execution is handled by callback to TriggerService.
    """

    @abstractmethod
    async def schedule_cron_trigger(
        self,
        trigger_id: UUID,
        cron_expression: str,
        timezone: str,
        callback: Callable[[UUID, Dict[str, Any]], None]
    ) -> None:
        """Schedule a cron trigger to fire at specified times"""
        pass

    @abstractmethod
    async def unschedule_trigger(self, trigger_id: UUID) -> None:
        """Remove a scheduled trigger"""
        pass

    @abstractmethod
    async def update_cron_schedule(
        self,
        trigger_id: UUID,
        cron_expression: str,
        timezone: str
    ) -> None:
        """Update the schedule for an existing trigger"""
        pass

    @abstractmethod
    async def get_trigger_status(self, trigger_id: UUID) -> Dict[str, Any]:
        """Get status of a scheduled trigger (next run time, etc.)"""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Check if the scheduler is healthy and operational"""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shutdown the scheduler"""
        pass
```

### 8. Implementation Examples

#### Temporal-Based Scheduler Implementation

#### Cron Trigger Workflow

```python
@workflow.defn
class CronTriggerWorkflow:
    def __init__(self):
        self.trigger_id: Optional[UUID] = None
        self.is_active: bool = True

    @workflow.run
    async def run(self, trigger_config: CronTriggerConfig) -> None:
        """Main workflow for cron-based triggers"""
        self.trigger_id = trigger_config.trigger_id

        while self.is_active:
            # Wait for next scheduled execution
            await workflow.sleep(self._calculate_next_delay(trigger_config.cron_expression))

            # Check if trigger is still active
            if not await workflow.execute_activity(
                check_trigger_active,
                self.trigger_id,
                start_to_close_timeout=timedelta(seconds=30)
            ):
                break

            # Execute trigger with retry logic
            await workflow.execute_activity(
                execute_trigger_activity,
                trigger_config,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=3
                )
            )

    @workflow.signal
    async def update_config(self, new_config: CronTriggerConfig) -> None:
        """Update trigger configuration"""
        # Signal to update cron expression or other settings
        pass

    @workflow.signal
    async def disable_trigger(self) -> None:
        """Disable the trigger"""
        self.is_active = False

    @workflow.query
    def get_status(self) -> dict:
        """Get current trigger status"""
        return {
            "trigger_id": str(self.trigger_id),
            "is_active": self.is_active,
            "last_execution": workflow.now()
        }
```

#### Temporal Activities

```python
@activity.defn
async def execute_trigger_activity(trigger_config: CronTriggerConfig) -> TriggerExecution:
    """Activity to execute a trigger and create agent task"""
    trigger_service = get_trigger_service()
    return await trigger_service.execute_trigger_by_id(
        trigger_config.trigger_id,
        {"execution_time": datetime.utcnow(), "source": "cron"}
    )

@activity.defn
async def check_trigger_active(trigger_id: UUID) -> bool:
    """Activity to check if trigger is still active"""
    trigger_service = get_trigger_service()
    trigger = await trigger_service.get_trigger(trigger_id)
    return trigger is not None and trigger.is_active

@activity.defn
async def validate_webhook_request_activity(
    webhook_data: WebhookRequestData
) -> WebhookValidationResult:
    """Activity to validate and process webhook requests"""
    webhook_manager = get_webhook_manager()
    return await webhook_manager.validate_and_process_request(webhook_data)
```

#### Temporal Scheduler Implementation

````python
class TemporalTriggerScheduler(TriggerScheduler):
    """Temporal-based implementation of TriggerScheduler interface"""

    def __init__(self, temporal_client: Client, execution_callback: TriggerExecutionCallback):
        self.client = temporal_client
        self.execution_callback = execution_callback
        self.active_workflows: Dict[UUID, WorkflowHandle] = {}

    async def start_cron_trigger(self, trigger: CronTrigger) -> None:
        """Start a Temporal workflow for cron trigger"""
        workflow_id = f"cron-trigger-{trigger.id}"

        handle = await self.client.start_workflow(
            CronTriggerWorkflow.run,
            CronTriggerConfig.from_trigger(trigger),
            id=workflow_id,
            task_queue="trigger-task-queue"
        )

        self.active_workflows[trigger.id] = handle

    async def stop_cron_trigger(self, trigger_id: UUID) -> None:
        """Stop a cron trigger workflow"""
        if trigger_id in self.active_workflows:
            handle = self.active_workflows[trigger_id]
            await handle.signal(CronTriggerWorkflow.disable_trigger)
            del self.active_workflows[trigger_id]

    async def update_cron_trigger(self, trigger: CronTrigger) -> None:
        """Update a cron trigger configuration"""
        if trigger_id in self.active_workflows:
            handle = self.active_workflows[trigger.id]
            await handle.signal(
                CronTriggerWorkflow.update_config,
                CronTriggerConfig.from_trigger(trigger)
            )

    async def get_trigger_status(self, trigger_id: UUID) -> Dict[str, Any]:
        """Get status of a cron trigger workflow"""
        if trigger_id in self.active_workflows:
            handle = self.active_workflows[trigger_id]
            return await handle.query(CronTriggerWorkflow.get_status)
        return {"status": "not_running"}

    async def is_healthy(self) -> bool:
        """Check Temporal connection health"""
        try:
            # Perform health check against Temporal
            return True
        except Exception:
            return False

    async def shutdown(self) -> None:
        """Gracefully shutdown all workflows"""
        for trigger_id in list(self.active_workflows.keys()):
            await self.stop_cron_trigger(trigger_id)

#### Alternative APScheduler Implementation

```python
class APSchedulerTriggerScheduler(TriggerScheduler):
    """APScheduler-based implementation for simpler deployments"""

    def __init__(self, scheduler: AsyncIOScheduler, execution_callback: TriggerExecutionCallback):
        self.scheduler = scheduler
        self.execution_callback = execution_callback
        self.active_jobs: Dict[UUID, str] = {}  # trigger_id -> job_id

    async def start_cron_trigger(self, trigger: CronTrigger) -> None:
        """Schedule cron trigger using APScheduler"""
        job = self.scheduler.add_job(
            self._execute_trigger,
            CronTrigger.from_crontab(trigger.cron_expression),
            args=[trigger.id],
            id=str(trigger.id),
            timezone=trigger.timezone
        )
        self.active_jobs[trigger.id] = job.id

    async def stop_cron_trigger(self, trigger_id: UUID) -> None:
        """Remove scheduled job"""
        if trigger_id in self.active_jobs:
            self.scheduler.remove_job(self.active_jobs[trigger_id])
            del self.active_jobs[trigger_id]

    async def _execute_trigger(self, trigger_id: UUID) -> None:
        """Execute trigger callback"""
        await self.execution_callback.execute_trigger(
            trigger_id,
            {"execution_time": datetime.utcnow(), "source": "cron"}
        )
`````

### 5. Webhook Manager Interface

#### Abstract Webhook Manager Interface

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class WebhookManager(ABC):
    """Abstract interface for webhook management implementations"""

    @abstractmethod
    def generate_webhook_url(self, trigger_id: UUID) -> str:
        """Generate unique webhook URL like /webhooks/abc123 for trigger"""
        pass

    @abstractmethod
    async def register_webhook(self, trigger: WebhookTrigger) -> None:
        """Register webhook trigger for incoming requests"""
        pass

    @abstractmethod
    async def unregister_webhook(self, webhook_id: str) -> None:
        """Unregister webhook trigger"""
        pass

    @abstractmethod
    async def handle_webhook_request(
        self,
        webhook_id: str,
        method: str,
        headers: Dict[str, str],
        body: Any,
        query_params: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Process incoming webhook request:
        1. Find trigger by webhook_id
        2. Parse request data (Telegram, Slack, GitHub, etc.)
        3. Call TriggerService to evaluate and execute
        4. Return HTTP response (200 OK, 400 Bad Request, etc.)
        """
        pass

    @abstractmethod
    async def validate_webhook_method(self, trigger: WebhookTrigger, method: str) -> bool:
        """Validate HTTP method against trigger's allowed methods"""
        pass

    @abstractmethod
    async def apply_validation_rules(self, trigger: WebhookTrigger, headers: Dict[str, str], body: Any) -> bool:
        """Apply trigger-specific validation rules to webhook request"""
        pass

    @abstractmethod
    async def apply_rate_limiting(self, webhook_id: str) -> bool:
        """Apply rate limiting to webhook requests"""
        pass

    @abstractmethod
    async def get_webhook_response(self, success: bool, error_message: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate appropriate HTTP response for webhook requests (Requirements 6.5, 7.4):
        - Returns HTTP 200 OK for successful trigger execution
        - Returns HTTP 400 Bad Request for validation failures
        - Returns HTTP 429 Too Many Requests for rate limiting
        - Returns HTTP 500 Internal Server Error for system failures
        - Includes appropriate response body for service-specific webhooks
        """
        pass

    @abstractmethod
    async def generate_service_specific_response(
        self,
        webhook_type: WebhookType,
        success: bool,
        execution_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate service-specific webhook responses (Requirement 7.4):
        - Telegram: Returns appropriate message format for bot responses
        - Slack: Returns proper Slack response format with optional message updates
        - GitHub: Returns standard GitHub webhook acknowledgment
        - Generic: Returns simple JSON success/error response
        """
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Check if the webhook manager is healthy and operational"""
        pass

class WebhookExecutionCallback(ABC):
    """Callback interface for webhook execution"""

    @abstractmethod
    async def execute_webhook_trigger(self, webhook_id: str, request_data: Dict[str, Any]) -> None:
        """Called when a webhook trigger should be executed"""
        pass
```

#### Predefined Webhook Integrations

The system uses a completely dynamic approach where webhook types are configured through user-uploaded JSON schemas (Requirements 7.1-7.5):

##### Dynamic Webhook Parser

```python
class DynamicWebhookParser:
    """Dynamic webhook parser that uses user-uploaded configurations"""

    def __init__(self, webhook_registry: WebhookTypeRegistry):
        self.webhook_registry = webhook_registry

    async def parse_webhook(self, webhook_type: str, method: str, headers: Dict[str, str], body: Any, query_params: Dict[str, str], webhook_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse webhook payload using dynamic configuration:
        - Load parsing rules from user-uploaded JSON schema
        - Apply custom parsing logic if provided
        - Extract data according to schema definition
        - Preserve original structure for LLM evaluation
        """
        type_config = self.webhook_registry.get_config(webhook_type)

        # Start with basic parsed data
        parsed_data = {
            "service": webhook_type,
            "method": method,
            "headers": headers,
            "query_params": query_params,
            "body": body,
            "content_type": headers.get("content-type", "unknown"),
            "raw_payload": {
                "method": method,
                "headers": headers,
                "body": body,
                "query_params": query_params
            }
        }

        # Apply custom parsing logic if provided
        if "custom_parser_code" in type_config and type_config["custom_parser_code"]:
            try:
                # Execute user-provided parsing code safely
                parsed_data.update(await self._execute_custom_parser(
                    type_config["custom_parser_code"],
                    body,
                    headers,
                    webhook_config
                ))
            except Exception as e:
                parsed_data["parse_error"] = str(e)

        # Validate against JSON schema
        if "json_schema" in type_config:
            try:
                self._validate_against_schema(body, type_config["json_schema"])
                parsed_data["schema_valid"] = True
            except Exception as e:
                parsed_data["schema_valid"] = False
                parsed_data["schema_error"] = str(e)

        return parsed_data

    async def validate_webhook(self, webhook_type: str, headers: Dict[str, str], body: Any, webhook_config: Dict[str, Any]) -> bool:
        """Validate webhook using dynamic configuration"""
        type_config = self.webhook_registry.get_config(webhook_type)

        # Check if validation is required
        if not type_config.get("validation_required", False):
            return True

        # Apply custom validation logic if provided
        if "validation_code" in type_config and type_config["validation_code"]:
            try:
                return await self._execute_custom_validation(
                    type_config["validation_code"],
                    headers,
                    body,
                    webhook_config
                )
            except Exception:
                return False

        # Basic validation - check required config fields are present
        required_fields = type_config.get("required_config_fields", [])
        for field in required_fields:
            if field not in webhook_config:
                return False

        return True

    async def _execute_custom_parser(self, parser_code: str, body: Any, headers: Dict[str, str], webhook_config: Dict[str, Any]) -> Dict[str, Any]:
        """Safely execute user-provided parsing code"""
        # This would implement safe code execution (sandboxed)
        # For now, return empty dict as placeholder
        return {}

    async def _execute_custom_validation(self, validation_code: str, headers: Dict[str, str], body: Any, webhook_config: Dict[str, Any]) -> bool:
        """Safely execute user-provided validation code"""
        # This would implement safe code execution (sandboxed)
        # For now, return True as placeholder
        return True

    def _validate_against_schema(self, data: Any, schema: Dict[str, Any]) -> None:
        """Validate data against JSON schema"""
        # This would use jsonschema library to validate
        pass
```

##### Webhook Type Configuration

```python
class WebhookTypeRegistry:
    """Dynamic registry for webhook type configurations loaded from user-uploaded schemas"""

    def __init__(self):
        self._webhook_types: Dict[str, Dict[str, Any]] = {}
        self._load_default_generic()

    def _load_default_generic(self):
        """Load only the generic webhook type by default"""
        self._webhook_types["generic"] = {
            "parser": "GenericWebhookParser",
            "required_config_fields": [],
            "default_methods": ["POST", "GET", "PUT", "DELETE"],
            "validation_required": False,
            "response_format": "json",
            "json_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": True
            }
        }

    async def register_webhook_type_from_schema(self, webhook_type: str, schema_config: Dict[str, Any]) -> None:
        """Register a new webhook type from user-uploaded JSON schema configuration"""
        # Validate the schema configuration
        required_fields = ["parser", "json_schema"]
        for field in required_fields:
            if field not in schema_config:
                raise ValueError(f"Missing required field: {field}")

        # Store the configuration
        self._webhook_types[webhook_type.lower()] = {
            "parser": schema_config["parser"],
            "required_config_fields": schema_config.get("required_config_fields", []),
            "default_methods": schema_config.get("default_methods", ["POST"]),
            "validation_required": schema_config.get("validation_required", False),
            "response_format": schema_config.get("response_format", "json"),
            "json_schema": schema_config["json_schema"],
            "custom_parser_code": schema_config.get("custom_parser_code"),  # Optional custom parsing logic
            "validation_code": schema_config.get("validation_code")  # Optional custom validation logic
        }

    def get_config(self, webhook_type: str) -> Dict[str, Any]:
        """Get configuration for a webhook type"""
        return self._webhook_types.get(webhook_type.lower(), self._webhook_types["generic"])

    def list_webhook_types(self) -> List[str]:
        """List all registered webhook types"""
        return list(self._webhook_types.keys())

    def remove_webhook_type(self, webhook_type: str) -> bool:
        """Remove a webhook type configuration"""
        if webhook_type.lower() == "generic":
            return False  # Cannot remove generic type
        return self._webhook_types.pop(webhook_type.lower(), None) is not None

# Example: User uploads webhook type configuration via API

# 1. User uploads Telegram webhook schema configuration:
telegram_schema = {
    "parser": "DynamicWebhookParser",
    "required_config_fields": ["bot_token"],
    "default_methods": ["POST"],
    "validation_required": True,
    "response_format": "json",
    "json_schema": {
        "type": "object",
        "properties": {
            "update_id": {"type": "integer"},
            "message": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "integer"},
                    "from": {"type": "object"},
                    "chat": {"type": "object"},
                    "text": {"type": "string"}
                }
            }
        },
        "required": ["update_id"]
    },
    "custom_parser_code": """
# User-provided parsing logic (executed safely)
def parse_telegram(body, headers, webhook_config):
    message = body.get('message', {})
    return {
        'chat_id': message.get('chat', {}).get('id'),
        'user_id': message.get('from', {}).get('id'),
        'text': message.get('text'),
        'has_document': 'document' in message
    }
""",
    "validation_code": """
# User-provided validation logic
def validate_telegram(headers, body, webhook_config):
    bot_token = webhook_config.get('bot_token')
    # Implement signature validation
    return bot_token is not None
"""
}

# Register the webhook type
await webhook_registry.register_webhook_type_from_schema("telegram", telegram_schema)

# 2. User creates webhook trigger using the registered type:
telegram_trigger = WebhookTrigger(
    name="My Telegram Bot",
    webhook_type="telegram",  # References user-uploaded schema
    webhook_config={
        "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "allowed_updates": ["message", "callback_query"]
    }
)

# 3. User uploads custom webhook schema for their service:
custom_service_schema = {
    "parser": "DynamicWebhookParser",
    "required_config_fields": ["api_key"],
    "default_methods": ["POST"],
    "validation_required": True,
    "response_format": "json",
    "json_schema": {
        "type": "object",
        "properties": {
            "event_type": {"type": "string"},
            "data": {"type": "object"},
            "timestamp": {"type": "string"}
        },
        "required": ["event_type", "data"]
    }
}

await webhook_registry.register_webhook_type_from_schema("my_service", custom_service_schema)

# 4. User creates trigger for their custom service:
custom_trigger = WebhookTrigger(
    name="My Custom Service Handler",
    webhook_type="my_service",
    webhook_config={
        "api_key": "my_secret_key",
        "filter_events": ["user_signup", "payment_completed"]
    }
)

# Example of how WebhookManager uses dynamic webhook configuration:

class WebhookManager:
    def __init__(self, webhook_registry: WebhookTypeRegistry):
        self.webhook_registry = webhook_registry
        self.dynamic_parser = DynamicWebhookParser(webhook_registry)

    async def process_webhook_request(self, trigger: WebhookTrigger, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process webhook request using dynamic configuration"""

        # Parse the request using dynamic parser
        parsed_data = await self.dynamic_parser.parse_webhook(
            webhook_type=trigger.webhook_type,
            method=request_data["method"],
            headers=request_data["headers"],
            body=request_data["body"],
            query_params=request_data["query_params"],
            webhook_config=trigger.webhook_config  # User's specific config
        )

        # Validate using dynamic configuration
        is_valid = await self.dynamic_parser.validate_webhook(
            webhook_type=trigger.webhook_type,
            headers=request_data["headers"],
            body=request_data["body"],
            webhook_config=trigger.webhook_config
        )

        return {
            "parsed_data": parsed_data,
            "is_valid": is_valid,
            "webhook_type": trigger.webhook_type
        }

# API endpoints for managing webhook type configurations:

class WebhookTypeController:
    """API endpoints for managing dynamic webhook type configurations"""

    async def upload_webhook_schema(self, webhook_type: str, schema_config: Dict[str, Any]) -> Dict[str, Any]:
        """Upload a new webhook type schema configuration"""
        try:
            await self.webhook_registry.register_webhook_type_from_schema(webhook_type, schema_config)
            return {"status": "success", "webhook_type": webhook_type}
        except ValueError as e:
            return {"status": "error", "message": str(e)}

    async def list_webhook_types(self) -> List[str]:
        """List all registered webhook types"""
        return self.webhook_registry.list_webhook_types()

    async def get_webhook_schema(self, webhook_type: str) -> Dict[str, Any]:
        """Get the schema configuration for a webhook type"""
        return self.webhook_registry.get_config(webhook_type)

    async def delete_webhook_type(self, webhook_type: str) -> Dict[str, Any]:
        """Delete a webhook type configuration"""
        success = self.webhook_registry.remove_webhook_type(webhook_type)
        return {"status": "success" if success else "error", "webhook_type": webhook_type}
```

### 6. LLM-Based Condition Evaluation

#### Natural Language Condition Processing

```python
class TriggerService:
    # ... existing methods ...

    async def evaluate_llm_condition(
        self,
        condition_text: str,
        event_data: Dict[str, Any],
        context: str = ""
    ) -> bool:
        """
        Use LLM to evaluate natural language conditions against event data.

        Examples:
        - "when user sends a file"
        - "if this looks like a sales inquiry"
        - "when message contains urgent request"
        - "if email is from a new customer"
        """
        prompt = f"""
        Evaluate if this condition is met based on the event data:

        Condition: {condition_text}
        Context: {context}

        Event Data:
        {json.dumps(event_data, indent=2)}

        Respond with only "true" or "false" and a brief explanation.
        """

        # Call LLM service
        response = await self.llm_service.evaluate(prompt)
        return response.lower().startswith("true")

    async def extract_task_parameters_with_llm(
        self,
        instruction: str,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Use LLM to extract relevant parameters from event data based on instruction.

        Example: "analyze the file and respond with insights"
        -> Extract file_url, chat_id, user_message, etc.
        """
        prompt = f"""
        Extract task parameters from this event data based on the instruction:

        Instruction: {instruction}

        Event Data:
        {json.dumps(event_data, indent=2)}

        Return a JSON object with relevant parameters for the task.
        """

        response = await self.llm_service.extract_parameters(prompt)
        return json.loads(response)
```

### 9. Dependency Injection and Configuration

#### Service Configuration

```python
from typing import Protocol

class TriggerServiceConfig(Protocol):
    """Configuration interface for trigger service"""
    scheduler_type: str  # "temporal", "apscheduler", "celery"
    webhook_manager_type: str  # "fastapi", "flask", "custom"

class TriggerServiceFactory:
    """Factory for creating TriggerService with appropriate implementations"""

    @staticmethod
    def create_trigger_service(
        config: TriggerServiceConfig,
        trigger_repository: TriggerRepository,
        task_service: TaskService,
        event_broker: EventBroker,
        agent_repository: AgentRepository,
    ) -> TriggerService:
        """Create TriggerService with configured implementations"""

        # Create scheduler based on configuration
        scheduler = TriggerServiceFactory._create_scheduler(config.scheduler_type)

        # Create webhook manager based on configuration
        webhook_manager = TriggerServiceFactory._create_webhook_manager(config.webhook_manager_type)

        return TriggerService(
            trigger_repository=trigger_repository,
            task_service=task_service,
            event_broker=event_broker,
            agent_repository=agent_repository,
            trigger_scheduler=scheduler,
            webhook_manager=webhook_manager,
        )

    @staticmethod
    def _create_scheduler(scheduler_type: str) -> TriggerScheduler:
        """Factory method for creating scheduler implementations"""
        if scheduler_type == "temporal":
            return TemporalTriggerScheduler(temporal_client, execution_callback)
        elif scheduler_type == "apscheduler":
            return APSchedulerTriggerScheduler(scheduler, execution_callback)
        else:
            raise ValueError(f"Unknown scheduler type: {scheduler_type}")

    @staticmethod
    def _create_webhook_manager(webhook_type: str) -> WebhookManager:
        """Factory method for creating webhook manager implementations"""
        if webhook_type == "fastapi":
            return FastAPIWebhookManager(webhook_callback)
        else:
            raise ValueError(f"Unknown webhook manager type: {webhook_type}")


```

#### Benefits of Interface-Driven Design

1. **Testability**: Easy to mock interfaces for unit testing
2. **Flexibility**: Different implementations for different environments
3. **Maintainability**: Changes to implementations don't affect core logic
4. **Extensibility**: New implementations can be added without modifying existing code
5. **Configuration-driven**: Implementation choice can be made at runtime through configuration

## Data Models

### Database Schema

#### Triggers Table

```sql
CREATE TABLE triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    agent_id UUID NOT NULL REFERENCES agents(id),
    trigger_type VARCHAR(50) NOT NULL, -- 'CRON', 'WEBHOOK'
    is_active BOOLEAN DEFAULT true,
    task_parameters JSONB DEFAULT '{}',
    conditions JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),

    -- Rate limiting and safety
    max_executions_per_hour INTEGER DEFAULT 60,
    failure_threshold INTEGER DEFAULT 5,
    consecutive_failures INTEGER DEFAULT 0,
    last_execution_at TIMESTAMP WITH TIME ZONE,

    -- Cron-specific fields
    cron_expression VARCHAR(255),
    timezone VARCHAR(100) DEFAULT 'UTC',
    next_run_time TIMESTAMP WITH TIME ZONE,

    -- Webhook-specific fields
    webhook_id VARCHAR(255) UNIQUE,
    allowed_methods TEXT[], -- ['POST', 'GET']
    webhook_type VARCHAR(50) DEFAULT 'GENERIC',
    validation_rules JSONB DEFAULT '{}',

    -- Generic webhook configuration - supports any webhook type
    webhook_config JSONB DEFAULT '{}',

    CONSTRAINT valid_trigger_type CHECK (trigger_type IN ('CRON', 'WEBHOOK')),
    CONSTRAINT cron_fields_required CHECK (
        (trigger_type != 'CRON') OR
        (cron_expression IS NOT NULL)
    ),
    CONSTRAINT webhook_fields_required CHECK (
        (trigger_type != 'WEBHOOK') OR
        (webhook_id IS NOT NULL)
    )
);

CREATE INDEX idx_triggers_agent_id ON triggers(agent_id);
CREATE INDEX idx_triggers_type_active ON triggers(trigger_type, is_active);
CREATE INDEX idx_triggers_webhook_id ON triggers(webhook_id);
CREATE INDEX idx_triggers_next_run ON triggers(next_run_time) WHERE trigger_type = 'CRON';
```

#### Trigger Executions Table

```sql
CREATE TABLE trigger_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_id UUID NOT NULL REFERENCES triggers(id) ON DELETE CASCADE,
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status VARCHAR(50) NOT NULL, -- 'SUCCESS', 'FAILED', 'TIMEOUT'
    task_id UUID REFERENCES tasks(id),
    execution_time_ms INTEGER,
    error_message TEXT,
    trigger_data JSONB DEFAULT '{}',
    workflow_id VARCHAR(255), -- Temporal workflow ID for correlation
    run_id VARCHAR(255),      -- Temporal run ID for correlation

    CONSTRAINT valid_execution_status CHECK (status IN ('SUCCESS', 'FAILED', 'TIMEOUT'))
);

CREATE INDEX idx_trigger_executions_trigger_id ON trigger_executions(trigger_id);
CREATE INDEX idx_trigger_executions_executed_at ON trigger_executions(executed_at);
CREATE INDEX idx_trigger_executions_status ON trigger_executions(status);
CREATE INDEX idx_trigger_executions_task_id ON trigger_executions(task_id);
```

## Error Handling

### Comprehensive Error Handling Strategy

The trigger system implements robust error handling at multiple levels to ensure system reliability and provide clear feedback (Requirements 1.4, 2.5, 4.4, 5.5, 8.5, 9.5):

#### 1. Trigger Creation Validation (Requirements 1.2, 1.4, 5.5)

**Agent Validation**:

- Verify agent exists in the system before trigger creation
- Check user permissions to access the specified agent
- Validate agent is in active state and available for task creation
- Return descriptive error: "Agent with ID {agent_id} not found or not accessible"

**Configuration Validation**:

- Validate trigger name uniqueness and format requirements
- Ensure event type is supported by the system
- Validate task parameters against agent requirements
- Return specific validation errors with field-level details

**Cron Expression Validation**:

- Parse and validate cron expression syntax using standard cron libraries
- Validate timezone settings and conversion capabilities
- Check for logical inconsistencies (e.g., February 30th)
- Return error: "Invalid cron expression '{expression}': {specific_error}"

**Webhook Configuration Validation**:

- Validate HTTP methods are supported (GET, POST, PUT, DELETE)
- Check webhook type is recognized or defaults to GENERIC
- Validate service-specific configurations (Telegram bot token format, etc.)
- Ensure validation rules are properly formatted JSON

**Condition Syntax Validation**:

- Validate rule-based condition syntax and field references
- Test LLM condition descriptions for clarity and evaluability
- Check condition logic operators and combinations
- Return syntax errors with line numbers and suggestions

#### 2. Runtime Execution Error Handling (Requirements 2.5, 4.4)

**Execution Failure Logging**:

- Record detailed error information including stack traces
- Capture event data and trigger configuration at time of failure
- Log LLM evaluation failures with prompt and response details
- Store error context for debugging and analysis

**Graceful Degradation**:

- Continue processing other triggers when individual triggers fail
- Isolate trigger failures to prevent system-wide impact
- Maintain service availability during partial failures
- Implement fallback mechanisms for critical operations

**Timeout Handling**:

- Configure activity timeouts for trigger execution (default: 5 minutes)
- Implement graceful timeout with proper resource cleanup
- Record timeout status in execution history with duration
- Cancel related Temporal workflows and activities on timeout

**Service Unavailability Handling**:

- Handle LLM service failures with retry logic and fallback
- Manage TaskService unavailability with queuing and retry
- Handle database connection failures with connection pooling
- Implement circuit breaker for external service dependencies

#### 3. Rate Limiting and Safety (Requirements 9.1, 9.2, 9.3, 9.5)

**Per-Trigger Rate Limiting**:

- Implement configurable execution limits per trigger (default: 60/hour)
- Track execution frequency with sliding window counters
- Block trigger execution when rate limit exceeded
- Log rate limit violations with trigger and time details

**Global Rate Limiting**:

- Apply system-wide limits for webhook endpoints
- Implement per-IP rate limiting for webhook requests
- Use distributed rate limiting for multi-instance deployments
- Return HTTP 429 with retry-after headers for rate limit violations

**Automatic Trigger Disabling**:

- Disable triggers after consecutive failures exceed threshold (default: 5)
- Send notifications to administrators when triggers are auto-disabled
- Provide manual re-enable capability after issue resolution
- Log auto-disable events with failure history and reasoning

**Execution Timeout Safety**:

- Implement configurable timeouts for trigger execution (default: 5 minutes)
- Cancel long-running operations to prevent resource exhaustion
- Record timeout events in execution history for monitoring
- Clean up resources and workflows on timeout

#### 4. Task Creation and Integration Errors (Requirements 2.5, 9.4)

**Task Creation Failures**:

- Log task creation failures with full context and parameters
- Continue processing other matching triggers independently
- Record failed executions in history with error details
- Implement retry logic for transient task creation failures

**Task Metadata Tracking**:

- Mark all created tasks with trigger metadata for tracking
- Include trigger ID, execution ID, and event data in task context
- Enable correlation between trigger executions and task results
- Support debugging of end-to-end automation workflows

**Integration Error Handling**:

- Handle TaskService API failures with appropriate retry logic
- Manage Temporal workflow creation failures with fallback
- Handle EventBroker publishing failures gracefully
- Implement compensation logic for partial failures

#### 5. Webhook-Specific Error Handling (Requirements 6.5, 7.4, 8.3)

**Request Validation Errors**:

- Validate HTTP method against trigger's allowed methods
- Apply request validation rules (required headers, body format)
- Handle malformed JSON and invalid content types
- Return appropriate HTTP status codes with error details

**Service-Specific Webhook Errors**:

- Handle Telegram webhook signature validation failures
- Manage Slack webhook verification token mismatches
- Process GitHub webhook secret validation errors
- Provide service-specific error responses and retry guidance

**Webhook Processing Errors**:

- Handle webhook URL not found (404) with clear error message
- Manage webhook trigger disabled scenarios gracefully
- Process multiple trigger execution failures independently
- Return appropriate HTTP responses to webhook callers

### Error Recovery Strategies

- **Temporal Retry Policies**: Built-in exponential backoff and retry mechanisms
- **Workflow Compensation**: Use Temporal's saga pattern for complex rollbacks
- **Circuit Breaker**: Disable triggers after consecutive failures (configurable threshold)
- **Dead Letter Queue**: Store failed executions for manual review via Temporal's failure handling
- **Alerting**: Notify administrators of critical failures through Temporal monitoring
- **Graceful Degradation**: Continue processing other triggers when individual triggers fail
- **Workflow Versioning**: Handle code changes without breaking running workflows

## Testing Strategy

### Unit Tests

1. **Trigger Service Tests**

   - CRUD operations
   - Validation logic
   - Execution flow

2. **Scheduler Tests**

   - Cron expression parsing
   - Job scheduling and execution
   - Timezone handling

3. **Webhook Manager Tests**

   - URL generation
   - Request parsing
   - Validation rules

4. **Parser Tests**
   - Telegram webhook parsing
   - Slack webhook parsing
   - Generic webhook handling

### Integration Tests

1. **End-to-End Trigger Execution**

   - Cron trigger → Task creation → Agent execution
   - Webhook trigger → Task creation → Agent execution

2. **Database Integration**

   - Trigger persistence
   - Execution history storage

3. **Event Publishing**
   - Trigger execution events
   - Task creation events

### Performance Tests

1. **High-Volume Webhook Handling**

   - Concurrent webhook requests
   - Rate limiting effectiveness

2. **Scheduler Performance**
   - Large number of cron triggers
   - Precise timing accuracy

## Security Considerations

### Webhook Security

1. **Authentication**: Optional webhook secret validation
2. **Rate Limiting**: Per-webhook and global rate limits
3. **Input Validation**: Sanitize all webhook inputs
4. **HTTPS Only**: Enforce secure webhook URLs in production

### Access Control

1. **Trigger Management**: Role-based access to trigger CRUD operations
2. **Agent Access**: Validate user permissions for target agents
3. **Execution Logs**: Secure access to trigger execution history

### Data Protection

1. **Sensitive Data**: Encrypt webhook secrets and configurations
2. **Audit Logging**: Log all trigger management operations
3. **Data Retention**: Configurable retention for execution history

## Monitoring and Observability

### Metrics

1. **Trigger Metrics**

   - Active trigger count by type
   - Execution success/failure rates
   - Average execution time

2. **Performance Metrics**
   - Webhook response times
   - Scheduler accuracy
   - Task creation latency

### Logging

1. **Structured Logging**: JSON-formatted logs with correlation IDs
2. **Log Levels**: Appropriate log levels for different events
3. **Error Context**: Detailed error information for debugging

### Execution History

The system provides comprehensive execution history tracking and querying capabilities (Requirements 4.1, 4.2, 4.3, 4.4):

1. **Execution Records**: Complete history of all trigger executions including:

   - Execution timestamp and duration
   - Execution status (SUCCESS, FAILED, TIMEOUT)
   - Event data that triggered the execution
   - Created task ID for correlation
   - Error details for failed executions
   - Temporal workflow and run IDs for debugging

2. **Task Correlation**: Direct linking between trigger executions and created agent tasks:

   - Track which trigger created which task
   - Enable end-to-end workflow tracing
   - Support debugging of complex automation chains
   - Provide audit trail for automated actions

3. **Advanced Filtering and Pagination**: Support for querying execution history with:

   - **Time-based filtering**: Filter by execution date ranges
   - **Status filtering**: Filter by execution status (success/failed/timeout)
   - **Trigger filtering**: Filter by specific trigger or trigger type
   - **Agent filtering**: Filter by target agent
   - **Error filtering**: Filter executions with specific error types
   - **Pagination**: Configurable page sizes with efficient database queries
   - **Sorting**: Sort by execution time, duration, status, or trigger name

4. **Performance Tracking**: Record and analyze execution metrics:

   - Average execution time per trigger
   - Success/failure rates over time
   - Peak execution periods and load patterns
   - Resource utilization during trigger execution
   - Trend analysis for trigger performance optimization

5. **Execution Context**: Store comprehensive context for each execution:
   - Original event data (webhook payload, cron schedule info)
   - Condition evaluation results and reasoning
   - LLM evaluation logs for natural language conditions
   - Task parameters passed to agent
   - Execution environment details (worker, timestamp, etc.)

### Health Checks

1. **Scheduler Health**: Verify scheduler is running and responsive
2. **Webhook Endpoint Health**: Test webhook URL accessibility
3. **Database Connectivity**: Monitor trigger storage health

## API Design

### REST API Endpoints

The trigger system exposes REST API endpoints following existing AgentArea patterns for trigger management and monitoring (Requirements 1.1, 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 3.4, 4.3):

#### Trigger Management Endpoints

```python
# Trigger CRUD Operations
POST   /api/v1/triggers                    # Create new trigger
GET    /api/v1/triggers                    # List triggers with filtering
GET    /api/v1/triggers/{trigger_id}       # Get specific trigger
PUT    /api/v1/triggers/{trigger_id}       # Update trigger configuration
DELETE /api/v1/triggers/{trigger_id}       # Delete trigger permanently

# Trigger Lifecycle Management
POST   /api/v1/triggers/{trigger_id}/enable   # Enable disabled trigger
POST   /api/v1/triggers/{trigger_id}/disable  # Disable active trigger

# Trigger Validation
POST   /api/v1/triggers/validate           # Validate trigger configuration before creation
POST   /api/v1/triggers/validate-cron      # Validate cron expression syntax
POST   /api/v1/triggers/validate-conditions # Validate trigger conditions syntax
```

#### Execution History and Monitoring Endpoints

```python
# Execution History (Requirement 4.3)
GET    /api/v1/triggers/{trigger_id}/executions     # Get execution history for specific trigger
GET    /api/v1/executions                           # Get all trigger executions with filtering
GET    /api/v1/executions/{execution_id}            # Get specific execution details

# Monitoring and Status
GET    /api/v1/triggers/{trigger_id}/status         # Get trigger status and next run time
GET    /api/v1/triggers/health                      # Health check for trigger system
GET    /api/v1/triggers/metrics                     # Trigger system metrics and statistics
```

#### Webhook Management Endpoints

```python
# Webhook-specific endpoints
GET    /api/v1/triggers/{trigger_id}/webhook-url    # Get webhook URL for trigger
POST   /api/v1/triggers/{trigger_id}/regenerate-webhook # Regenerate webhook URL

# Webhook request handling (Requirements 6.1-6.5, 7.1-7.5)
POST   /webhooks/{webhook_id}                       # Generic webhook endpoint
GET    /webhooks/{webhook_id}                       # Support GET webhooks if configured
PUT    /webhooks/{webhook_id}                       # Support PUT webhooks if configured
```

#### API Request/Response Models

```python
# Trigger Creation Request
class CreateTriggerRequest:
    name: str
    description: str
    agent_id: UUID
    trigger_type: TriggerType
    task_parameters: dict[str, Any]
    conditions: dict[str, Any]

    # Cron-specific fields
    cron_expression: Optional[str] = None
    timezone: Optional[str] = "UTC"

    # Webhook-specific fields
    allowed_methods: Optional[list[str]] = ["POST"]
    webhook_type: Optional[WebhookType] = WebhookType.GENERIC
    validation_rules: Optional[dict[str, Any]] = {}

# Trigger Response Model
class TriggerResponse:
    id: UUID
    name: str
    description: str
    agent_id: UUID
    trigger_type: TriggerType
    is_active: bool
    task_parameters: dict[str, Any]
    conditions: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: str

    # Execution statistics
    total_executions: int
    successful_executions: int
    failed_executions: int
    last_execution_at: Optional[datetime]
    next_run_time: Optional[datetime]  # For cron triggers
    webhook_url: Optional[str]         # For webhook triggers

# Execution History Request with Filtering (Requirement 4.3)
class ExecutionHistoryRequest:
    trigger_id: Optional[UUID] = None
    status: Optional[ExecutionStatus] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    page: int = 1
    page_size: int = 50
    sort_by: str = "executed_at"
    sort_order: str = "desc"

# Execution History Response (Requirements 4.1, 4.2, 4.3, 4.4)
class ExecutionHistoryResponse:
    executions: list[TriggerExecutionResponse]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool

class TriggerExecutionResponse:
    id: UUID
    trigger_id: UUID
    trigger_name: str
    executed_at: datetime
    status: ExecutionStatus
    task_id: Optional[UUID]
    execution_time_ms: int
    error_message: Optional[str]
    trigger_data: dict[str, Any]
    workflow_id: Optional[str]
    run_id: Optional[str]
```

#### API Error Handling

The API implements comprehensive error handling with descriptive error messages (Requirements 1.4, 2.5, 4.4, 5.5):

```python
# Standard API Error Response
class APIErrorResponse:
    error_code: str
    error_message: str
    details: Optional[dict[str, Any]] = None
    timestamp: datetime
    request_id: str

# Specific Error Scenarios
HTTP_400_BAD_REQUEST:
    - Invalid trigger configuration
    - Invalid cron expression syntax
    - Invalid condition syntax
    - Agent does not exist
    - Unsupported event type

HTTP_404_NOT_FOUND:
    - Trigger not found
    - Execution record not found

HTTP_409_CONFLICT:
    - Trigger name already exists
    - Webhook URL already in use

HTTP_429_TOO_MANY_REQUESTS:
    - Rate limit exceeded for webhook requests
    - Too many trigger executions per hour

HTTP_500_INTERNAL_SERVER_ERROR:
    - Database connection failure
    - Temporal service unavailable
    - LLM service failure
    - Task creation failure
```

## Deployment Considerations

### Temporal Configuration

1. **Temporal Connection**

   - Temporal server endpoint
   - Namespace configuration
   - TLS/authentication settings

2. **Worker Configuration**

   - Task queue names
   - Worker concurrency limits
   - Activity timeouts and retry policies

3. **Workflow Settings**
   - Workflow execution timeout
   - Signal/query handling
   - Workflow versioning strategy

### Configuration

1. **Environment Variables**

   - Temporal connection settings
   - Webhook base URL
   - Rate limiting parameters
   - Worker pool configuration

2. **Feature Flags**
   - Enable/disable trigger types
   - Predefined webhook support
   - Temporal workflow features

### Scaling

1. **Temporal Workers**: Scale workers horizontally across multiple instances
2. **Workflow Distribution**: Temporal automatically distributes workflows across workers
3. **Database Performance**: Optimized queries and indexing
4. **Webhook Load Balancing**: Distribute webhook requests across instances
5. **Temporal Cluster**: Leverage Temporal's built-in clustering for high availability

### Migration Strategy

1. **Database Migrations**: Alembic migrations for trigger tables
2. **Backward Compatibility**: Graceful handling of existing system
3. **Feature Rollout**: Gradual enablement of trigger functionality
