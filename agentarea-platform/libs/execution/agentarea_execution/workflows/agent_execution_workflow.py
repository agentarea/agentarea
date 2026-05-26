import json
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_agents_sdk.skills import SkillActivationTool, SkillCatalogBuilder, SkillEntry
    from agentarea_agents_sdk.tools.disclosure import (
        DisclosureContext,
        NamedLookupPolicy,
        RevealRequest,
        ToolCandidate,
        ToolDisclosurePolicy,
    )
    from agentarea_agents_sdk.tools.tool_catalog import ToolCatalog
    from agentarea_agents_sdk.tools.tool_provider import (
        AgentToolProvider,
        BuiltinToolProvider,
        CodeToolProvider,
        MCPToolProvider,
    )
    from agentarea_common.money import serialize_money

    from .context_manager import (
        ContextWindowManager,
        find_compaction_boundary,
        validate_tool_pairs,
    )
    from .context_strategy import (
        ContextStrategy,
        allows_history_preservation,
        allows_output_offloading,
        allows_tool_progressive_disclosure,
        resolve_context_strategy,
    )
    from .helpers import (
        BudgetTracker,
        EventManager,
        MessageBuilder,
        StateValidator,
        ToolCallExtractor,
        build_output_summary,
    )
    from .models import (
        AgentExecutionState,
        AgentGoal,
        ContinueAsNewState,
        Message,
        PendingEscalation,
        ToolCall,
    )

from ..models import (
    AgentConfigRequest,
    AgentConfigResult,
    AgentExecutionRequest,
    AgentExecutionResult,
    ChangeModelPayload,
    CompactMessagesRequest,
    CompactMessagesResult,
    CreateDelegationTaskRequest,
    CreateDelegationTaskResult,
    DiscoverToolProvidersResult,
    ExecuteSkillScriptRequest,
    ExecuteSkillScriptResult,
    LLMCallRequest,
    LLMCallResult,
    MCPToolRequest,
    ReadOutputRequest,
    ReadOutputResult,
    RecallHistoryRequest,
    RecallHistoryResult,
    ResolveAgentToolsRequest,
    ResolveAgentToolsResult,
    ResolveModelRequest,
    SearchHistoryRequest,
    SearchHistoryResult,
    SkillFileRequest,
    SkillFileResult,
    StoreHistoryRequest,
    StoreHistoryResult,
    StoreOutputRequest,
    StoreOutputResult,
    ToolDiscoveryRequest,
    ToolDiscoveryResult,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
)
from .constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    DELEGATION_TIMEOUT,
    EVENT_PUBLISH_RETRY_ATTEMPTS,
    EVENT_PUBLISH_TIMEOUT,
    HEARTBEAT_TIMEOUT,
    LLM_CALL_TIMEOUT,
    LLM_RETRY_ATTEMPTS,
    MAX_ITERATIONS,
    TOOL_EXECUTION_TIMEOUT,
    TOOL_OUTPUT_OFFLOAD_CHARS,
    Activities,
    EventTypes,
    ExecutionStatus,
)


@workflow.defn
class AgentExecutionWorkflow:
    """Agent execution workflow without ADK dependency."""

    def __init__(self):
        self.state = AgentExecutionState()
        self.event_manager: EventManager | None = None
        self.budget_tracker: BudgetTracker | None = None
        self.context_manager: ContextWindowManager | None = None
        self._paused = False
        self._pause_reason = ""
        self._awaiting_input = False
        # Metadata passed in at workflow start (set in _initialize_workflow).
        # Used to detect e.g. agent_delegation children that must terminate
        # immediately on completion rather than entering await_input.
        self._workflow_metadata: dict[str, Any] = {}
        # Maps sanitized agent tool names to their config (type=agent entries)
        self._agent_tool_registry: dict[str, dict] = {}
        # A2UI action queue — frontend signals land here, workflow loop drains them
        self._a2ui_action_queue: list[dict[str, Any]] = []
        self._skill_tool: SkillActivationTool | None = None
        self._tool_catalog: ToolCatalog | None = None
        # OpenAPI disclosure: NamedLookupPolicy when pool is non-empty, else None.
        # Stateless wrt the policy itself — pool lives in state.searchable_tool_pool.
        self._disclosure_policy: ToolDisclosurePolicy | None = None
        self._pending_escalations: dict[str, PendingEscalation] = {}
        # Generic message queue — queued user messages drained before each LLM call
        self._message_queue: list[dict[str, Any]] = []
        # Track if completion event has been published (to avoid double-publish at termination)
        self._completion_event_published = False

    @workflow.signal
    async def pause_execution(self, reason: str = "Paused by user") -> None:
        """Signal to pause execution."""
        self._paused = True
        self._pause_reason = reason
        workflow.logger.info(f"Workflow paused: {reason}")

        # Add event for pause
        if self.event_manager:
            self.event_manager.add_event(
                "execution_paused",
                {
                    "reason": reason,
                    "iteration": self.state.current_iteration,
                },
            )
            # We can't await async functions in signal handlers usually,
            # but we can modify state that the workflow loop will see.
            # However, we should try to publish this event if possible or just let the loop handle it.
            # Since we are in a signal handler, we should keep it simple.

    @workflow.signal
    async def resume_execution(self, reason: str = "Resumed by user") -> None:
        """Signal to resume execution."""
        self._paused = False
        self._pause_reason = ""
        workflow.logger.info(f"Workflow resumed: {reason}")

        # Add event for resume
        if self.event_manager:
            self.event_manager.add_event(
                "execution_resumed",
                {
                    "reason": reason,
                    "iteration": self.state.current_iteration,
                },
            )

    _MAX_A2UI_QUEUE_SIZE = 50

    @workflow.signal
    async def handle_a2ui_action(self, action_data: dict) -> None:
        """Signal from frontend when user interacts with an A2UI surface.

        The action is queued and injected as a user message on the next LLM call,
        so the agent can respond to the user's interaction.
        """
        if len(self._a2ui_action_queue) >= self._MAX_A2UI_QUEUE_SIZE:
            workflow.logger.warning("A2UI action queue full, dropping oldest")
            self._a2ui_action_queue.pop(0)
        self._a2ui_action_queue.append(action_data)
        workflow.logger.info(
            f"A2UI action received: {action_data.get('name', 'unknown')} "
            f"on surface {action_data.get('surface_id', 'unknown')}"
        )

    @workflow.signal
    async def resolve_escalation(
        self, escalation_id: str, approved: bool, comment: str = ""
    ) -> None:
        """Signal to approve or deny a specific tool escalation."""
        if escalation_id in self._pending_escalations:
            esc = self._pending_escalations[escalation_id]
            esc.resolved = True
            esc.approved = approved
            esc.deny_comment = comment if not approved else None

            # Emit resolved event so history load knows the outcome
            event_type = (
                EventTypes.HUMAN_APPROVAL_RECEIVED if approved else EventTypes.HUMAN_APPROVAL_DENIED
            )
            self.event_manager.add_event(
                event_type,
                {
                    "escalation_id": escalation_id,
                    "tool_name": esc.tool_name,
                    "tool_call_id": esc.tool_call_id,
                    "approved": approved,
                    "comment": comment,
                    "iteration": self.state.current_iteration,
                },
            )
            workflow.logger.info(
                f"Escalation {escalation_id} resolved: approved={approved}"
                + (f" comment='{comment}'" if comment else "")
            )

    @workflow.signal
    async def workflow_command(self, command: str, payload: dict) -> None:
        """Generic command signal for mid-execution control."""
        handlers = {
            "change_model": self._handle_change_model,
            "update_budget": self._handle_update_budget,
            "queue_message": self._handle_queue_message,
            "remove_message": self._handle_remove_message,
        }
        handler = handlers.get(command)
        if handler:
            handler(payload)
            if self.event_manager:
                self.event_manager.add_event(
                    EventTypes.WORKFLOW_COMMAND_RECEIVED,
                    {
                        "command": command,
                        "iteration": self.state.current_iteration,
                    },
                )
        else:
            workflow.logger.warning(f"Unknown workflow command: {command}")

    def _handle_change_model(self, payload: dict) -> None:
        """Handle a change_model command: update cached model info and agent config."""
        info = ChangeModelPayload(**payload)
        old = self.state.resolved_model
        self.state.resolved_model = info.model_dump()
        self.state.agent_config["model_id"] = info.model_id
        if info.context_window != self.state.context_window:
            self.state.context_window = info.context_window
            if self.context_manager:
                self.context_manager = ContextWindowManager(info.context_window)
        if self.event_manager:
            self.event_manager.add_event(
                EventTypes.MODEL_CHANGED,
                {
                    "old_model": old.get("model_name") if old else None,
                    "new_model": info.model_name,
                    "new_model_id": info.model_id,
                },
            )
        workflow.logger.info(
            f"Model changed: {old.get('model_name') if old else 'none'} -> {info.model_name}"
        )

    def _handle_update_budget(self, payload: dict) -> None:
        """Handle an update_budget command (stub for future use)."""
        pass

    def _handle_queue_message(self, payload: dict) -> None:
        """Queue a user message for the agent's next iteration."""
        msg_id = str(workflow.uuid4())
        # Accept both "message" and "content" keys for robustness
        text = payload.get("message") or payload.get("content") or ""
        if not text:
            workflow.logger.warning("queue_message received with empty text, ignoring")
            return
        self._message_queue.append({"id": msg_id, "content": text})
        if self.event_manager:
            self.event_manager.add_event(
                "MessageQueued",
                {
                    "message_id": msg_id,
                    "content": text,
                },
            )
        workflow.logger.info(f"Message queued: {msg_id}")

    def _handle_remove_message(self, payload: dict) -> None:
        """Remove a queued message by ID before the agent sees it."""
        msg_id = payload["message_id"]
        self._message_queue = [m for m in self._message_queue if m["id"] != msg_id]
        if self.event_manager:
            self.event_manager.add_event(
                "MessageRemoved",
                {"message_id": msg_id},
            )
        workflow.logger.info(f"Message removed from queue: {msg_id}")

    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Main workflow execution method."""
        try:
            # Initialize workflow
            await self._initialize_workflow(request)

            # Main execution loop
            result = await self._execute_main_loop()

            # Finalize and return result
            return await self._finalize_execution(result)

        except Exception as e:
            workflow.logger.error(f"Workflow execution failed: {e}")
            await self._handle_workflow_error(e)
            raise

    async def _initialize_workflow(self, request: AgentExecutionRequest) -> None:
        """Initialize workflow state and dependencies."""
        workflow.logger.info(f"Initializing workflow for agent {request.agent_id}")

        # Check if this is a continue-as-new restart
        if request.continued_state:
            await self._restore_from_continued_state(request.continued_state)
            return

        # Populate state attributes
        self.state.execution_id = workflow.info().workflow_id
        self.state.agent_id = str(request.agent_id)
        self.state.task_id = str(request.task_id)
        self.state.user_id = request.user_id
        self.state.workspace_id = request.workspace_id  # Add workspace_id from request
        self.state.goal = self._build_goal_from_request(request)
        self.state.status = ExecutionStatus.INITIALIZING
        self.state.budget_usd = request.budget_usd
        self.state.effective_policy = request.effective_policy
        self._workflow_metadata = dict(request.workflow_metadata or {})

        # Initialize helpers
        self.event_manager = EventManager(
            task_id=self.state.task_id,
            agent_id=self.state.agent_id,
            execution_id=self.state.execution_id,
        )
        self.budget_tracker = BudgetTracker(self.state.budget_usd)

        # Add workflow started event
        self.event_manager.add_event(
            EventTypes.WORKFLOW_STARTED,
            {
                "goal_description": self.state.goal.description,
                "max_iterations": self.state.goal.max_iterations,
                "budget_limit": serialize_money(self.budget_tracker.budget_limit),
            },
        )

        # Publish immediately
        await self._publish_events_immediately()

        # Initialize agent configuration
        await self._initialize_agent_config()

    async def _initialize_agent_config(self) -> None:
        """Initialize agent configuration and available tools."""
        workflow.logger.info("Initializing agent configuration")

        # Prepare user context data for activities
        # Use actual user_id and workspace_id from the request
        self.state.user_context_data = {
            "user_id": self.state.user_id,
            "workspace_id": self.state.workspace_id,
        }

        # Build agent config using Pydantic request model
        agent_config_request = AgentConfigRequest(
            agent_id=UUID(self.state.agent_id), user_context_data=self.state.user_context_data
        )
        agent_config_result: AgentConfigResult = await workflow.execute_activity(
            Activities.BUILD_AGENT_CONFIG,
            args=[agent_config_request],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

        # Convert result to dict for state storage (supports Pydantic BaseModel or plain dict)
        try:
            self.state.agent_config = agent_config_result.model_dump()
        except AttributeError:
            self.state.agent_config = dict(agent_config_result)

        # Store context window in state and initialize context manager
        self.state.context_window = self.state.agent_config.get("context_window", 128000)
        self.context_manager = ContextWindowManager(self.state.context_window)

        # Resolve model info once and cache in state to avoid per-call DB lookups
        model_id = self.state.agent_config.get("model_id")
        if model_id:
            try:
                resolve_model_request = ResolveModelRequest(
                    model_id=model_id,
                    workspace_id=self.state.workspace_id,
                )
                self.state.resolved_model = await workflow.execute_activity(
                    Activities.RESOLVE_MODEL,
                    args=[resolve_model_request],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
                )
                workflow.logger.info(
                    f"Model resolved and cached: {self.state.resolved_model.get('model_name')}"
                )
            except Exception as e:
                workflow.logger.warning(
                    f"Could not pre-resolve model {model_id}, will fall back to per-call lookup: {e}"
                )
                self.state.resolved_model = None

        # Validate configuration
        if not StateValidator.validate_agent_config(self.state.agent_config):
            raise ApplicationError("Invalid agent configuration")

        # Resolve context strategy early — gates tool discovery mode
        strategy = resolve_context_strategy(
            self.state.agent_config.get("context_strategy"),
            self.state.agent_config.get("default_context_strategy"),
        )
        self.state.context_strategy = strategy.value

        tools_request = ToolDiscoveryRequest(
            agent_id=UUID(self.state.agent_id), user_context_data=self.state.user_context_data
        )

        if allows_tool_progressive_disclosure(strategy):
            # DYNAMIC mode: discover providers, build catalog, inject only catalog + activate tool
            providers_result: DiscoverToolProvidersResult = await workflow.execute_activity(
                Activities.DISCOVER_TOOL_PROVIDERS,
                args=[tools_request],
                result_type=DiscoverToolProvidersResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

            # Reconstruct ToolProviders from serialized data
            providers = []
            for pd in providers_result.providers:
                provider_map = {
                    "mcp": lambda d: MCPToolProvider(name=d.name, instance_id="", tools=d.tools),
                    "code": lambda d: CodeToolProvider(name=d.name, tools=d.tools),
                    "agent": lambda d: AgentToolProvider(name=d.name, agent_id="", tools=d.tools),
                    "builtin": lambda d: BuiltinToolProvider(name=d.name, tools=d.tools),
                }
                factory = provider_map.get(pd.provider_type)
                if factory:
                    providers.append(factory(pd))

            # Build catalog with previously activated sources carried from continue-as-new
            activated = set(getattr(self.state, "activated_tool_sources", []) or [])
            self._tool_catalog = ToolCatalog(providers, activated=activated)

            # Start with tools from already-activated sources + builtin tools
            available_tools: list[dict[str, Any]] = []
            for p in providers:
                if p.provider_type == "builtin" or p.name in activated:
                    available_tools.extend(p.get_tool_definitions())

            # Add activate_tool_source tool
            available_tools.append(self._tool_catalog.get_activate_tool_source_definition())

        else:
            # STATIC/HYBRID mode: load all tools upfront (current behavior)
            tools_result: ToolDiscoveryResult = await workflow.execute_activity(
                Activities.DISCOVER_AVAILABLE_TOOLS,
                args=[tools_request],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

            # Normalize tools to list[dict] for state storage, accepting multiple shapes
            available_tools: list[dict[str, Any]] = []
            try:
                tools_list = tools_result.tools  # Expected ToolDiscoveryResult
            except AttributeError:
                tools_list = tools_result  # Fallback: activity returned a raw list

            for tool in tools_list or []:
                try:
                    available_tools.append(tool.model_dump())  # Pydantic ToolDefinition
                except AttributeError:
                    if isinstance(tool, dict):
                        available_tools.append(tool)
                    else:
                        # Last resort: convert object to dict via __dict__
                        try:
                            available_tools.append(dict(tool.__dict__))
                        except Exception:  # noqa: S110
                            pass

            # Searchable OpenAPI pool — operations marked load_mode=searchable
            # are deferred behind a `load_tools` meta-tool. The catalog text
            # (added later, alongside skill catalog) and the meta-tool
            # together let the LLM ask for schemas on demand.
            searchable_entries_raw: list[dict[str, Any]] = []
            try:
                raw_entries = tools_result.searchable_entries
            except AttributeError:
                raw_entries = []
            for entry in raw_entries or []:
                if hasattr(entry, "model_dump"):
                    searchable_entries_raw.append(entry.model_dump(by_alias=True))
                elif isinstance(entry, dict):
                    searchable_entries_raw.append(entry)
            if searchable_entries_raw:
                self.state.searchable_tool_pool = searchable_entries_raw
                self._disclosure_policy = NamedLookupPolicy()
                meta_tools = self._disclosure_policy.get_meta_tool_definitions(
                    DisclosureContext(
                        model_name=str(self.state.agent_config.get("model_id", "")),
                        context_window=self.state.context_window,
                        iteration=self.state.current_iteration,
                    )
                )
                available_tools.extend(meta_tools)

        # === Built-in completion tool (always present, canonical definition) ===
        # Remove any existing completion/task_complete from discovery — we always
        # use our own definition with correct description and required params.
        completion_tool_definition = {
            "type": "function",
            "function": {
                "name": "completion",
                "description": (
                    "Finish the task and send your response to the user. "
                    "The 'result' parameter is the message the user will see — "
                    "write it as a complete, helpful answer (not a summary or status). "
                    "You MUST call this tool when you are done."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Your complete response to the user. This is what they will read.",
                        },
                    },
                    "required": ["result"],
                },
            },
        }
        available_tools = [
            t
            for t in available_tools
            if (t.get("function", {}).get("name") if t.get("type") == "function" else t.get("name"))
            not in {"completion", "task_complete"}
        ]
        available_tools.insert(0, completion_tool_definition)

        # recall_history — query past execution context
        available_tools.append(
            {
                "type": "function",
                "function": {
                    "name": "recall_history",
                    "description": (
                        "Recall context from past executions of this task. "
                        "Use when you need information that may have been compacted "
                        "out of the current conversation, or to review what happened "
                        "in earlier execution attempts. Supports grep to search stored history."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Optional search query to describe what you're looking for",
                            },
                            "event_types": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Filter by event types (e.g. ToolCallCompleted, LLMCallCompleted)",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max events to return (default 20)",
                            },
                            "grep": {
                                "type": "string",
                                "description": "Regex pattern to search stored message history (searches MinIO history chunks)",
                            },
                            "tool_name": {
                                "type": "string",
                                "description": "Filter stored history to messages from a specific tool",
                            },
                        },
                    },
                },
            }
        )

        # Inject read_tool_output for retrieving offloaded large outputs (hybrid/dynamic)
        if allows_output_offloading(strategy):
            available_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "read_tool_output",
                        "description": (
                            "Read a previously stored tool output. Use when you see "
                            "'[Output stored as ...]' in a tool result and need the full content. "
                            "Supports grep filtering and head/tail slicing."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "output_id": {
                                    "type": "string",
                                    "description": "The output ID from the stored result reference",
                                },
                                "grep": {
                                    "type": "string",
                                    "description": "Filter lines matching this regex pattern",
                                },
                                "head": {
                                    "type": "integer",
                                    "description": "Return only first N lines",
                                },
                                "tail": {
                                    "type": "integer",
                                    "description": "Return only last N lines",
                                },
                            },
                            "required": ["output_id"],
                        },
                    },
                }
            )

        # Inject built-in activate_skill tool for progressive skill disclosure
        skills = self.state.agent_config.get("skills", [])
        if skills:
            skill_entries = [
                SkillEntry(
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    content=s.get("content", ""),
                    files=s.get("files", []),
                )
                for s in (s.model_dump() if hasattr(s, "model_dump") else s for s in skills)
            ]
            registry = SkillCatalogBuilder.build_registry(skill_entries)
            self._skill_tool = SkillActivationTool(registry)
            available_tools.append(self._skill_tool.get_openai_function_definition())

            # Inject run_skill_script tool for executing skill-bundled scripts
            available_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "run_skill_script",
                        "description": (
                            "Execute a script bundled with an activated skill in an isolated sandbox. "
                            "The skill must be activated first via activate_skill."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_name": {
                                    "type": "string",
                                    "description": "Name of the activated skill that owns the script",
                                },
                                "script_name": {
                                    "type": "string",
                                    "description": "Filename of the script to run (e.g. calculator.py)",
                                },
                                "args": {
                                    "type": "string",
                                    "description": "Arguments to pass to the script",
                                },
                                "artifact_paths": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": (
                                        "Relative output files to upload as task artifacts after the script runs"
                                    ),
                                },
                            },
                            "required": ["skill_name", "script_name"],
                        },
                    },
                }
            )

        self.state.available_tools = available_tools

        if not StateValidator.validate_tools(self.state.available_tools):
            raise ApplicationError("Invalid tools configuration")

        # Resolve agent tools for workflow-level delegation
        await self._resolve_agent_tools()

    async def _resolve_agent_tools(self) -> None:
        """Build agent tool registry by resolving agent names to IDs.

        Identifies agent-type tools from config and resolves their IDs
        so the workflow can start child workflows directly instead of
        routing through the activity-level polling delegation.
        """
        tools_config = self.state.agent_config.get("tools", [])
        agent_names = [
            tc.get("name")
            for tc in tools_config
            if isinstance(tc, dict) and tc.get("type") == "agent" and tc.get("name")
        ]

        if not agent_names:
            return

        resolve_request = ResolveAgentToolsRequest(
            agent_names=agent_names,
            workspace_id=self.state.workspace_id,
            user_context_data=self.state.user_context_data,
        )

        result: ResolveAgentToolsResult = await workflow.execute_activity(
            Activities.RESOLVE_AGENT_TOOLS,
            args=[resolve_request],
            result_type=ResolveAgentToolsResult,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

        # Build registry: sanitized tool name → {agent_id, agent_name, config}
        import re

        for agent_name, agent_id in result.agent_map.items():
            sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", agent_name)
            sanitized = re.sub(r"_+", "_", sanitized).strip("_")
            if not sanitized or sanitized[0].isdigit():
                sanitized = f"agent_{sanitized}"
            tool_name = f"delegate_to_{sanitized}"

            self._agent_tool_registry[tool_name] = {
                "agent_id": agent_id,
                "agent_name": agent_name,
            }

        if self._agent_tool_registry:
            workflow.logger.info(
                f"Registered {len(self._agent_tool_registry)} agent tools for delegation: "
                f"{list(self._agent_tool_registry.keys())}"
            )

    async def _restore_from_continued_state(self, continued_state: dict) -> None:
        """Restore workflow state from a continue-as-new restart."""
        workflow.logger.info("Restoring workflow from continue-as-new state")

        state = ContinueAsNewState(**continued_state)

        self.state.execution_id = state.execution_id
        self.state.agent_id = state.agent_id
        self.state.task_id = state.task_id
        self.state.user_id = state.user_id
        self.state.workspace_id = state.workspace_id
        self.state.goal = state.goal
        self.state.agent_config = state.agent_config
        self.state.available_tools = state.available_tools
        self.state.current_iteration = state.current_iteration
        self.state.budget_usd = state.budget_usd
        self.state.context_window = state.context_window
        self.state.user_context_data = state.user_context_data
        self.state.activated_skills = state.activated_skills
        self.state.context_strategy = state.context_strategy
        self.state.history_chunk_counter = state.history_chunk_counter
        self.state.activated_tool_sources = state.activated_tool_sources
        self.state.searchable_tool_pool = state.searchable_tool_pool
        self.state.revealed_openapi_tools = state.revealed_openapi_tools
        # Re-instantiate disclosure policy stateless from pool presence so
        # post-replay tool dispatch can route load_tools and rebuild the
        # catalog block on subsequent iterations.
        if self.state.searchable_tool_pool:
            self._disclosure_policy = NamedLookupPolicy()
            # Reconcile previously revealed names against the restored pool.
            # If a connection's `available_tools` shrunk between runs, drop the
            # stale schema from `available_tools`, drop the name from the
            # revealed list, and warn — otherwise the LLM would see a tool it
            # can no longer execute.
            pool_names = {c["name"] for c in self.state.searchable_tool_pool}
            stale = [
                name
                for name in self.state.revealed_openapi_tools
                if name not in pool_names
            ]
            if stale:
                workflow.logger.warning(
                    "Dropping %d stale revealed OpenAPI tool(s) on continue-as-new: %s",
                    len(stale),
                    stale,
                )
                stale_set = set(stale)
                self.state.revealed_openapi_tools = [
                    n for n in self.state.revealed_openapi_tools if n not in stale_set
                ]
                self.state.available_tools = [
                    t
                    for t in self.state.available_tools
                    if (t.get("function", {}) or {}).get("name") not in stale_set
                ]
        self.state.service_budget_usd = state.service_budget_usd
        self.state.service_cost_used = state.service_cost_used
        self.state.wallet_id = state.wallet_id
        self.state.resolved_model = state.resolved_model
        self.state.effective_policy = state.effective_policy
        self.state.status = ExecutionStatus.EXECUTING

        # Restore messages from compacted dicts
        self.state.messages = [Message(**msg) for msg in state.messages]

        # Restore agent tool registry for delegation routing
        self._agent_tool_registry = state.agent_tool_registry

        # Restore skill activation tool from agent_config
        skills = self.state.agent_config.get("skills", [])
        if skills:
            skill_entries = [
                SkillEntry(
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    content=s.get("content", ""),
                    files=s.get("files", []),
                )
                for s in skills
            ]
            registry = SkillCatalogBuilder.build_registry(skill_entries)
            self._skill_tool = SkillActivationTool(registry)
            # Mark already-activated skills from state
            for name in self.state.activated_skills:
                if name in self._skill_tool._skills_registry:
                    self._skill_tool._activated.add(name)

        # Initialize helpers with restored cost
        self.event_manager = EventManager(
            task_id=self.state.task_id,
            agent_id=self.state.agent_id,
            execution_id=self.state.execution_id,
        )
        self.budget_tracker = BudgetTracker(self.state.budget_usd)
        self.budget_tracker.add_cost(state.total_cost)
        self.context_manager = ContextWindowManager(self.state.context_window)

        workflow.logger.info(
            f"Restored from run {state.continued_from_run_id}, "
            f"iteration {state.current_iteration}, "
            f"cost ${state.total_cost:.4f}, "
            f"{len(self.state.messages)} messages, "
            f"{len(self._agent_tool_registry)} agent tools"
        )

    async def _continue_as_new(self) -> None:
        """Compact messages and continue workflow with fresh event history."""
        workflow.logger.info(
            f"Continue-as-new triggered at iteration {self.state.current_iteration}, "
            f"event history suggests reset"
        )

        # Compact messages before carrying state forward
        await self._compact_context_if_needed()

        # Serialize messages to dicts
        messages_dict = [
            MessageBuilder.normalize_message_dict(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                    "tool_calls": msg.tool_calls,
                }
            )
            for msg in self.state.messages
        ]

        continued_state = ContinueAsNewState(
            execution_id=self.state.execution_id,
            agent_id=self.state.agent_id,
            task_id=self.state.task_id,
            user_id=self.state.user_id,
            workspace_id=self.state.workspace_id,
            goal=self.state.goal,
            messages=messages_dict,
            agent_config=self.state.agent_config,
            available_tools=self.state.available_tools,
            current_iteration=self.state.current_iteration,
            total_cost=serialize_money(self.budget_tracker.cost),
            budget_usd=self.state.budget_usd,
            context_window=self.state.context_window,
            user_context_data=self.state.user_context_data,
            continued_from_run_id=workflow.info().run_id,
            agent_tool_registry=self._agent_tool_registry,
            activated_skills=self.state.activated_skills,
            context_strategy=self.state.context_strategy,
            history_chunk_counter=self.state.history_chunk_counter,
            activated_tool_sources=self.state.activated_tool_sources,
            searchable_tool_pool=self.state.searchable_tool_pool,
            revealed_openapi_tools=self.state.revealed_openapi_tools,
            service_budget_usd=self.state.service_budget_usd,
            service_cost_used=self.state.service_cost_used,
            wallet_id=self.state.wallet_id,
            resolved_model=self.state.resolved_model,
            effective_policy=self.state.effective_policy,
        )

        # Publish event before continuing (persisted in DB via tier 2)
        self.event_manager.add_event(
            EventTypes.WORKFLOW_CONTINUED_AS_NEW,
            {
                "iteration": self.state.current_iteration,
                "total_cost": serialize_money(self.budget_tracker.cost),
                "messages_carried": len(self.state.messages),
                "continued_from_run_id": workflow.info().run_id,
                "reason": "Temporal event history size limit approaching",
            },
        )
        await self._publish_events_immediately()

        # Build new request with continued state
        new_request = AgentExecutionRequest(
            task_id=UUID(self.state.task_id),
            agent_id=UUID(self.state.agent_id),
            user_id=self.state.user_id,
            workspace_id=self.state.workspace_id,
            task_query=self.state.goal.description if self.state.goal else "",
            max_reasoning_iterations=self.state.goal.max_iterations
            if self.state.goal
            else MAX_ITERATIONS,
            budget_usd=self.state.budget_usd,
            effective_policy=self.state.effective_policy,
            continued_state=continued_state.model_dump(),
        )

        workflow.continue_as_new(args=[new_request])

    async def _execute_main_loop(self) -> dict[str, Any]:
        """Main execution loop with dynamic termination conditions.

        After the agent calls task_complete, the workflow enters awaiting_input
        state instead of terminating. It waits for follow-up user messages
        (via queue_message signal) or times out after AWAIT_INPUT_TIMEOUT.
        """
        workflow.logger.info("Starting main execution loop")

        self.state.status = ExecutionStatus.EXECUTING

        while True:
            # Increment iteration count
            self.state.current_iteration += 1

            # Check if we should continue before starting the iteration
            should_continue, reason = self._should_continue_execution()
            if not should_continue:
                workflow.logger.info(
                    f"Stopping execution before iteration {self.state.current_iteration}: {reason}"
                )
                # Decrement since we didn't actually execute this iteration
                self.state.current_iteration -= 1
                break

            workflow.logger.info(f"Starting iteration {self.state.current_iteration}")

            # Execute iteration
            await self._execute_iteration()

            # If agent completed the task, wait for follow-up messages.
            # Exception: a workflow spawned via agent delegation has no
            # end-user owning its conversation — its parent is awaiting the
            # result via execute_child_workflow. Sitting in await_input
            # would block the parent until DELEGATION_TIMEOUT cancels us.
            # Future "mode=conversation" delegations would opt in here.
            if self._awaiting_input:
                if self._is_delegation_child():
                    workflow.logger.info("Delegated child completed — exiting without await_input")
                    break
                await self._await_follow_up()
                # If we got a new message, continue the loop
                if not self._awaiting_input:
                    # Reset success so the loop continues with new message
                    self.state.success = False
                    self.state.status = ExecutionStatus.EXECUTING
                    continue
                # Timed out — exit the loop
                break

            # Check if we should finish after completing the iteration
            should_continue, reason = self._should_continue_execution()
            if not should_continue:
                workflow.logger.info(
                    f"Stopping execution after iteration {self.state.current_iteration}: {reason}"
                )
                break

            # Check if Temporal suggests resetting event history
            if workflow.info().is_continue_as_new_suggested():
                await self._continue_as_new()
                # continue_as_new raises an exception internally, so we won't reach here

            # Check for pause
            if self._paused:
                await workflow.wait_condition(lambda: not self._paused)

        return {"iterations_completed": self.state.current_iteration}

    def _is_delegation_child(self) -> bool:
        """True iff this workflow was spawned via parent's delegation tool.

        Identified by ``workflow_metadata.source == "agent_delegation"`` set
        in ``_execute_agent_delegation``. Such children have no end-user
        owning their conversation, so they must not enter await_input.
        """
        return (self._workflow_metadata or {}).get("source") == "agent_delegation"

    async def _await_follow_up(self) -> None:
        """Wait for a follow-up user message or timeout.

        The workflow idles here consuming zero worker resources. Temporal
        persists the state and wakes the workflow on signal or timeout.
        Uses try/except per Temporal SDK docs (TimeoutError on timeout).
        """
        from datetime import timedelta

        workflow.logger.info("Task completed — waiting for follow-up messages (30 min timeout)")

        try:
            await workflow.wait_condition(
                lambda: len(self._message_queue) > 0,
                timeout=timedelta(minutes=30),
            )
        except TimeoutError:
            workflow.logger.info("Await timeout reached, finalizing workflow")
            return

        workflow.logger.info("Follow-up message received, resuming execution")
        self._awaiting_input = False

        # Update task status back to running
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
                UpdateTaskStatusRequest(
                    task_id=self.state.task_id,
                    status="running",
                    workspace_id=self.state.workspace_id,
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

    def _should_continue_execution(self) -> tuple[bool, str]:
        """Comprehensive check for whether execution should continue.

        Checks all termination conditions:
        - Goal achievement
        - Maximum iterations reached
        - Budget exceeded
        - Workflow cancelled/paused state

        Returns:
            tuple[bool, str]: (should_continue, reason_for_stopping)
        """
        # Debug logging
        workflow.logger.info(
            f"Checking termination conditions - success: "
            f"{self.state.success} (type: {type(self.state.success)}), "
            f"iteration: {self.state.current_iteration}"
        )
        workflow.logger.info(f"State object id: {id(self.state)}")

        # Check if goal is achieved (highest priority)
        if self.state.success:
            workflow.logger.info("Goal achieved - terminating workflow")
            return False, "Goal achieved successfully"

        # Check maximum iterations
        max_iterations = self.state.goal.max_iterations if self.state.goal else MAX_ITERATIONS
        if self.state.current_iteration > max_iterations:
            workflow.logger.info(
                f"Max iterations reached ({max_iterations}) - terminating workflow"
            )
            return False, f"Maximum iterations reached ({max_iterations})"

        # Check budget constraints
        if self.budget_tracker and self.budget_tracker.is_exceeded():
            workflow.logger.info("Budget exceeded - terminating workflow")
            return (
                False,
                f"Budget exceeded (${self.budget_tracker.cost:.2f}/${self.budget_tracker.budget_limit:.2f})",
            )

        # Check for cancellation (this could be extended for other cancellation conditions)
        # For now, we don't have explicit cancellation, but this is where it would go

        # If we get here, execution should continue
        return True, "Continue execution"

    async def _execute_iteration(self) -> None:
        """Execute a single iteration."""
        iteration = self.state.current_iteration

        self.event_manager.add_event(
            EventTypes.ITERATION_STARTED,
            {
                "iteration": iteration,
                "budget_remaining": serialize_money(self.budget_tracker.get_remaining()),
            },
        )
        await self._publish_events_immediately()

        try:
            await self._execute_traditional_iteration()

            # Check budget warnings
            await self._check_budget_status()

            self.event_manager.add_event(
                EventTypes.ITERATION_COMPLETED,
                {"iteration": iteration, "total_cost": serialize_money(self.budget_tracker.cost)},
            )

            # Emit WorkflowCompleted after IterationCompleted for conversational agents.
            # Stateless runs publish the completion event from _finalize_execution.
            if self._awaiting_input:
                self.event_manager.add_event(
                    EventTypes.WORKFLOW_COMPLETED,
                    {
                        "success": True,
                        "iterations_completed": self.state.current_iteration,
                        "total_cost": serialize_money(self.budget_tracker.cost),
                        "result": self.state.final_response,
                    },
                )
                self._completion_event_published = True

        except Exception as e:
            error_details = self._extract_temporal_error_details(e)
            workflow.logger.error(
                f"Iteration {iteration} failed: {error_details}",
                exc_info=True,
            )
            self.event_manager.add_event(
                EventTypes.LLM_CALL_FAILED,
                {"iteration": iteration, "error": error_details},
            )
            raise

        await self._publish_events_immediately()

    async def _execute_traditional_iteration(self) -> None:
        """Execute iteration using traditional LLM + tool approach."""
        iteration = self.state.current_iteration

        # Build system prompt with agent context and current task
        if self.state.goal:
            # Build instruction with skills appended
            agent_instruction = self.state.agent_config.get(
                "instruction", "You are a helpful AI assistant."
            )

            # Append skill catalog (progressive disclosure — full content
            # loaded on-demand via the activate_skill tool)
            if self._skill_tool:
                skill_entries = list(self._skill_tool._skills_registry.values())
                catalog_text = SkillCatalogBuilder.build_catalog(skill_entries)
                agent_instruction = agent_instruction + catalog_text

            # Append tool source catalog for progressive disclosure (DYNAMIC mode)
            if self._tool_catalog:
                tool_catalog_text = self._tool_catalog.build_prompt_text()
                if tool_catalog_text:
                    agent_instruction = agent_instruction + tool_catalog_text

            project_id = (self._workflow_metadata or {}).get("project_id")
            if project_id:
                agent_instruction += (
                    "\n\nProject input files are available to shell commands in the "
                    "`inputs/` directory of the sandbox. Use ordinary file operations "
                    "such as `find inputs -maxdepth 2 -type f` to inspect them. "
                    "When a shell command creates a file that should be returned to "
                    "the user, pass that relative file path in the shell tool's "
                    "`artifact_paths` argument so it is stored as a task artifact."
                )

            # Append OpenAPI operation catalog (load_mode=searchable, issue #115).
            # Pool lives in workflow state; only this name+description block is
            # sent to the LLM until it explicitly calls load_tools(...).
            if self._disclosure_policy and self.state.searchable_tool_pool:
                ctx = DisclosureContext(
                    model_name=str(self.state.agent_config.get("model_id", "")),
                    context_window=self.state.context_window,
                    iteration=self.state.current_iteration,
                )
                pool = [ToolCandidate(**c) for c in self.state.searchable_tool_pool]
                openapi_catalog_text = self._disclosure_policy.render_catalog(pool, ctx)
                if openapi_catalog_text:
                    agent_instruction = agent_instruction + openapi_catalog_text

            system_prompt = MessageBuilder.build_system_prompt(
                agent_name=self.state.agent_config.get("name", "AI Agent"),
                agent_instruction=agent_instruction,
                goal_description=self.state.goal.description,
                success_criteria=self.state.goal.success_criteria,
                available_tools=self.state.available_tools,
                a2ui_enabled=self.state.agent_config.get("a2ui_enabled", False),
            )

            # Add system message and user message if first iteration
            if iteration == 1:
                # Create messages directly using the Message class
                self.state.messages.append(Message(role="system", content=system_prompt))
                self.state.messages.append(
                    Message(role="user", content=self.state.goal.description)
                )
            # else:
            #     # Add status update for subsequent iterations (not in system prompt)
            #     # Avoid importing PromptBuilder to prevent Temporal sandbox issues
            #     status_msg = f"Iteration {iteration}/{self.state.goal.max_iterations} | Budget remaining: ${self.budget_tracker.get_remaining():.2f}"
            #     # Status updates are just regular user messages in conversation context
            #     self.state.messages.append(
            #         Message(role="user", content=f"Status: {status_msg}")
            #     )

        # Check context window and compact if needed (skip first iteration)
        if self.context_manager and iteration > 1:
            messages_dict_est = [
                {"role": msg.role, "content": msg.content or ""} for msg in self.state.messages
            ]
            estimated = self.context_manager.estimate_usage(messages_dict_est)
            self.context_manager.update_usage(estimated)

            if self.context_manager.needs_compaction():
                await self._compact_context_if_needed()
            elif self.context_manager.should_warn():
                self.event_manager.add_event(
                    EventTypes.CONTEXT_WARNING,
                    {
                        "iteration": self.state.current_iteration,
                        "usage_ratio": self.context_manager.get_usage_ratio(),
                        "message_count": len(self.state.messages),
                    },
                )
                await self._publish_events_immediately()
                self.context_manager.mark_warning_sent()

        # Drain queued A2UI actions as user messages so the LLM can respond
        if self._a2ui_action_queue:
            import json as _json

            for action in self._a2ui_action_queue:
                action_msg = (
                    f"[A2UI Action] The user interacted with the UI surface "
                    f"'{action.get('surface_id', 'unknown')}': "
                    f"action={action.get('name', 'unknown')}, "
                    f"source={action.get('source_component_id', 'unknown')}, "
                    f"context={_json.dumps(action.get('context', {}))}"
                )
                self.state.messages.append(Message(role="user", content=action_msg))
            self._a2ui_action_queue.clear()

        # Drain queued user messages into conversation before calling LLM
        if self._message_queue:
            for msg in self._message_queue:
                self.state.messages.append(Message(role="user", content=msg["content"]))
            self._message_queue.clear()

        # Call LLM
        llm_response = await self._call_llm()

        # Process LLM response
        await self._process_llm_response(llm_response)

    async def _call_llm(self) -> dict[str, Any]:
        """Call LLM with conversation context using Pydantic models."""
        workflow.logger.info(f"Calling LLM in iteration {self.state.current_iteration}")

        # Add event for LLM call start
        self.event_manager.add_event(
            EventTypes.LLM_CALL_STARTED,
            {
                "iteration": self.state.current_iteration,
                "message_count": len(self.state.messages),
            },
        )
        await self._publish_events_immediately()

        try:
            # Convert messages to dict format for LLM call - filter out None values to match agent SDK format
            messages_dict = [
                MessageBuilder.normalize_message_dict(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                        "name": msg.name,
                        "tool_calls": msg.tool_calls,
                    }
                )
                for msg in self.state.messages
            ]

            # Create Pydantic request model
            llm_request = LLMCallRequest(
                messages=messages_dict,
                model_id=self.state.agent_config.get("model_id"),
                tools=self.state.available_tools,
                workspace_id=self.state.user_context_data["workspace_id"],
                user_context_data=self.state.user_context_data,
                temperature=None,
                max_tokens=None,
                task_id=self.state.task_id,
                agent_id=self.state.agent_id,
                execution_id=self.state.execution_id,
                resolved_model=self.state.resolved_model,
                effective_policy=self.state.effective_policy,
            )

            response: LLMCallResult = await workflow.execute_activity(
                Activities.CALL_LLM,
                args=[llm_request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=LLM_RETRY_ATTEMPTS),
            )

            # Normalize response fields to support both Pydantic model and plain dict
            if isinstance(response, dict):
                raw_usage = response.get("usage")
                cost_value = response.get("cost", 0.0)
                role_value = response.get("role", "assistant")
                content_value = response.get("content", "")
                thinking_value = response.get("thinking", "")
                tool_calls_value = response.get("tool_calls")
            else:
                raw_usage = getattr(response, "usage", None)
                cost_value = getattr(response, "cost", 0.0)
                role_value = getattr(response, "role", "assistant")
                content_value = getattr(response, "content", "")
                thinking_value = getattr(response, "thinking", "")
                tool_calls_value = getattr(response, "tool_calls", None)

            # Extract usage info and update budget
            if raw_usage is None:
                usage_payload = {}
            else:
                # raw_usage may be a Pydantic model or a plain dict-like object
                try:
                    usage_payload = raw_usage.model_dump()  # Pydantic BaseModel
                except AttributeError:
                    try:
                        if isinstance(raw_usage, dict):
                            usage_payload = raw_usage
                        else:
                            usage_payload = dict(raw_usage.__dict__)
                    except Exception:
                        usage_payload = {}

            usage_info = {
                "cost": cost_value,
                "usage": usage_payload,
            }
            self.budget_tracker.add_cost(usage_info["cost"])

            # Update context window manager with actual token usage
            if self.context_manager and usage_payload:
                prompt_tokens = usage_payload.get("prompt_tokens", 0)
                if prompt_tokens > 0:
                    self.context_manager.update_usage(prompt_tokens)

            # Strip A2UI JSON from the content sent to frontend via LLM_CALL_COMPLETED
            display_content = content_value
            if self.state.agent_config.get("a2ui_enabled", False) and content_value:
                from .a2ui_parser import A2UI_DELIMITER

                if A2UI_DELIMITER in content_value:
                    display_content = content_value.split(A2UI_DELIMITER, 1)[0].rstrip()

            self.event_manager.add_event(
                EventTypes.LLM_CALL_COMPLETED,
                {
                    "iteration": self.state.current_iteration,
                    "cost": usage_info["cost"],
                    "total_cost": serialize_money(self.budget_tracker.cost),
                    "usage": usage_info,
                    "content": display_content,
                    "thinking": thinking_value,
                    "tool_calls": tool_calls_value or [],
                    "role": role_value,
                },
            )
            await self._publish_events_immediately()

            # Return dict for compatibility with existing code
            return {
                "role": role_value,
                "content": content_value,
                "tool_call_id": None,  # Not provided by LLM response
                "name": None,  # Not provided by LLM response
                "tool_calls": tool_calls_value,
                "usage": usage_info,
                "cost": cost_value,
            }

        except Exception as e:
            # Simplified error handling - enriched error events are now published by the activity
            error_message = self._extract_temporal_error_details(e)
            error_lower = error_message.lower()

            is_provider_quota_block = (
                "insufficient balance" in error_lower
                or "no resource package" in error_lower
                or "quota exceeded" in error_lower
            )

            # Generic LLM error event for workflow tracking
            user_error = self._get_user_facing_error(e)
            self.event_manager.add_event(
                EventTypes.LLM_CALL_FAILED,
                {
                    "iteration": self.state.current_iteration,
                    "error": user_error,
                    "error_type": self._get_user_facing_error_type(e),
                    "model_id": self.state.agent_config.get("model_id"),
                },
            )

            if is_provider_quota_block:
                self.state.status = ExecutionStatus.BLOCKED
                self.state.blocked_reason = user_error
                self.event_manager.add_event(
                    EventTypes.WORKFLOW_FAILED,
                    {
                        "error": user_error,
                        "error_type": "ProviderQuotaExceeded",
                        "blocked": True,
                        "blocked_reason": user_error,
                        "retryable": False,
                    },
                )

            await self._publish_events_immediately()
            raise

    async def _process_llm_response(self, response: dict[str, Any]) -> None:
        """Process LLM response and handle tool calls."""
        # Only add non-empty messages to state
        content = response.get("content", "")
        tool_calls_raw = response.get("tool_calls")
        thinking_value = response.get("thinking", "")

        # Parse and publish A2UI events if agent has A2UI enabled
        if self.state.agent_config.get("a2ui_enabled", False) and content:
            from .a2ui_parser import A2UI_DELIMITER, parse_a2ui_response

            if A2UI_DELIMITER in content:
                a2ui_result = parse_a2ui_response(content)
                if a2ui_result.a2ui_events:
                    # Replace content with text-only portion
                    content = a2ui_result.text_content
                    response["content"] = content

                    # Publish each A2UI event through the existing pipeline
                    for a2ui_event in a2ui_result.a2ui_events:
                        event_data = {k: v for k, v in a2ui_event.items() if k != "type"}
                        event_data["task_id"] = str(self.state.task_id)
                        self.event_manager.add_event(a2ui_event["type"], event_data)

                    await self._publish_events_immediately()

                if a2ui_result.parse_error:
                    workflow.logger.warning(f"A2UI parse error: {a2ui_result.parse_error}")

        # Use thinking as content fallback when model returns only reasoning
        # (some models like GLM return reasoning_content without content/tool_calls)
        effective_content = content
        if not effective_content.strip() and not tool_calls_raw and thinking_value:
            effective_content = thinking_value
            workflow.logger.info(
                "LLM returned thinking without content/tools — using thinking as content"
            )

        if effective_content.strip() or tool_calls_raw:
            # Create Message directly from response dict
            self.state.messages.append(
                Message(
                    role=response.get("role", "assistant"),
                    content=effective_content,
                    tool_calls=tool_calls_raw,
                )
            )
        else:
            workflow.logger.warning(
                f"Received empty LLM response in iteration {self.state.current_iteration}"
            )

        # Extract and execute tool calls - pass the response dict directly
        tool_calls = ToolCallExtractor.extract_tool_calls(response)

        if tool_calls:
            await self._execute_tool_calls(tool_calls)
        elif effective_content.strip():
            # LLM responded with text/thinking but no tool calls.
            # This IS the agent's response — treat it as implicit completion.
            # Most agent frameworks (Claude Code, Cline, OpenCode) work this way:
            # text response = answer to user, no explicit completion tool needed.
            workflow.logger.info("LLM responded with text only — treating as implicit completion")
            completion_call = ToolCall(
                id=str(workflow.uuid4()),
                function={
                    "name": "completion",
                    "arguments": json.dumps({"result": effective_content.strip()}),
                },
            )
            await self._handle_task_completion(completion_call)
            return
        else:
            # No content, no thinking, no tool calls — truly empty response
            workflow.logger.error(
                f"LLM returned empty response with no tool calls in iteration {self.state.current_iteration}"
            )

    async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> None:
        """Execute tools, running agent delegations in parallel.

        Agent delegations are started concurrently as child workflows.
        Regular MCP/code tools run sequentially (they may have side effects
        that depend on execution order).
        """
        import asyncio

        completion_call = None
        agent_calls: list[ToolCall] = []
        regular_calls: list[ToolCall] = []
        recall_calls: list[ToolCall] = []
        skill_calls: list[ToolCall] = []
        script_calls: list[ToolCall] = []
        read_output_calls: list[ToolCall] = []
        activate_source_calls: list[ToolCall] = []
        load_tools_calls: list[ToolCall] = []

        for tool_call in tool_calls:
            tool_name = tool_call.function["name"]
            if tool_name in {"completion", "task_complete"}:
                completion_call = tool_call
            elif tool_name == "recall_history":
                recall_calls.append(tool_call)
            elif tool_name == "read_tool_output":
                read_output_calls.append(tool_call)
            elif tool_name == "activate_tool_source":
                activate_source_calls.append(tool_call)
            elif tool_name == "load_tools":
                load_tools_calls.append(tool_call)
            elif tool_name == "activate_skill":
                skill_calls.append(tool_call)
            elif tool_name == "run_skill_script":
                script_calls.append(tool_call)
            elif tool_name in self._agent_tool_registry:
                agent_calls.append(tool_call)
            else:
                regular_calls.append(tool_call)

        # Run recall_history and read_tool_output calls (can run in parallel with agent calls)
        for tool_call in recall_calls:
            await self._execute_recall_history(tool_call)

        for tool_call in read_output_calls:
            await self._execute_read_tool_output(tool_call)

        # Execute tool source activations (DYNAMIC mode — local, no activity)
        for tool_call in activate_source_calls:
            await self._execute_activate_tool_source(tool_call)

        # Execute OpenAPI load_tools meta-calls (issue #115 — local, no activity)
        for tool_call in load_tools_calls:
            await self._execute_load_openapi_tools(tool_call)

        # Execute skill activations (local, no activity needed)
        for tool_call in skill_calls:
            await self._execute_skill_activation(tool_call)

        # Execute skill scripts (via MCP Manager sandbox)
        for tool_call in script_calls:
            await self._execute_skill_script(tool_call)

        # Run agent delegations in parallel (fan-out)
        if agent_calls:
            if len(agent_calls) == 1:
                await self._execute_agent_delegation(agent_calls[0])
            else:
                workflow.logger.info(
                    f"Fan-out: delegating to {len(agent_calls)} agents in parallel"
                )
                tasks = [self._execute_agent_delegation(tc) for tc in agent_calls]
                await asyncio.gather(*tasks)

        # Run regular tools sequentially
        for tool_call in regular_calls:
            await self._execute_mcp_tool(tool_call)

        # Handle completion last
        if completion_call:
            await self._handle_task_completion(completion_call)

    async def _handle_task_completion(self, completion_call: ToolCall) -> None:
        """Handle task completion and optionally wait for follow-ups."""
        try:
            tool_args = json.loads(completion_call.function["arguments"])
            result_text = tool_args.get("result", "Task completed")
        except (json.JSONDecodeError, KeyError):
            result_text = "Task completed"

        self.state.success = True
        self.state.final_response = result_text
        agent_type = str(self.state.agent_config.get("agent_type") or "stateless").lower()
        self._awaiting_input = agent_type == "stateful"

        workflow.logger.info(f"Task completed: {result_text}")
        if self._awaiting_input:
            workflow.logger.info("Entering awaiting_input state for follow-up messages")

        # Update task status to completed immediately so UI reflects it
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
                UpdateTaskStatusRequest(
                    task_id=self.state.task_id,
                    status="completed",
                    result=json.dumps({"response": result_text}),
                    workspace_id=self.state.workspace_id,
                    total_cost=serialize_money(self.budget_tracker.cost)
                    if self.budget_tracker
                    else "0",
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

    async def _execute_mcp_tool(self, tool_call: ToolCall) -> None:
        """Execute a single MCP tool call using Pydantic models."""
        tool_name = tool_call.function["name"]

        # Parse arguments
        import json

        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        # Approval gating before starting the tool activity
        requires_approval = self._tool_requires_approval(tool_name)
        workflow.logger.info(
            f"Tool '{tool_name}' approval check: requires_approval={requires_approval}, "
            f"agent_config tools={len((self.state.agent_config or {}).get('tools', []))}"
        )
        approval_required = (
            bool(self.state.goal and getattr(self.state.goal, "requires_human_approval", False))
            or requires_approval
        )

        if approval_required:
            escalation_id = str(workflow.uuid4())
            escalation = PendingEscalation(
                escalation_id=escalation_id,
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                tool_args=tool_args,
            )
            self._pending_escalations[escalation_id] = escalation

            self.state.status = ExecutionStatus.WAITING_FOR_APPROVAL

            # Persist approval status to DB so inbox can query it
            await workflow.execute_activity(
                Activities.UPDATE_TASK_STATUS,
                args=[
                    UpdateTaskStatusRequest(
                        task_id=self.state.task_id,
                        status="waiting_for_approval",
                        workspace_id=self.state.workspace_id,
                    )
                ],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

            # Publish approval requested event with escalation_id
            self.event_manager.add_event(
                EventTypes.HUMAN_APPROVAL_REQUESTED,
                {
                    "escalation_id": escalation_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "iteration": self.state.current_iteration,
                    "arguments": tool_args,
                    "message": f"Tool '{tool_name}' requires human approval",
                },
            )
            await self._publish_events_immediately()

            # Wait for THIS specific escalation to be resolved
            await workflow.wait_condition(lambda: escalation.resolved)

            if not escalation.approved:
                # Denied — add tool result as denied, don't execute
                deny_msg = escalation.deny_comment or "Denied by user"
                self.event_manager.add_event(
                    EventTypes.HUMAN_APPROVAL_DENIED,
                    {
                        "escalation_id": escalation_id,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.id,
                        "iteration": self.state.current_iteration,
                        "comment": deny_msg,
                    },
                )
                await self._publish_events_immediately()

                # Add denied result as tool response so LLM knows
                self.state.messages.append(
                    Message(
                        role="tool",
                        content=f"Tool call denied by human operator: {deny_msg}",
                        tool_call_id=tool_call.id,
                        name=tool_name,
                    )
                )

                # Clean up and update status
                del self._pending_escalations[escalation_id]
                if not self._pending_escalations:
                    self.state.status = ExecutionStatus.EXECUTING
                    await workflow.execute_activity(
                        Activities.UPDATE_TASK_STATUS,
                        args=[
                            UpdateTaskStatusRequest(
                                task_id=self.state.task_id,
                                status="running",
                                workspace_id=self.state.workspace_id,
                            )
                        ],
                        start_to_close_timeout=ACTIVITY_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
                    )
                return

            # Approved — continue to execute
            self.event_manager.add_event(
                EventTypes.HUMAN_APPROVAL_RECEIVED,
                {
                    "escalation_id": escalation_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "iteration": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()
            del self._pending_escalations[escalation_id]
            if not self._pending_escalations:
                self.state.status = ExecutionStatus.EXECUTING
                await workflow.execute_activity(
                    Activities.UPDATE_TASK_STATUS,
                    args=[
                        UpdateTaskStatusRequest(
                            task_id=self.state.task_id,
                            status="running",
                            workspace_id=self.state.workspace_id,
                        )
                    ],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
                )

        # Publish tool call started event (only after approval if required)
        self.event_manager.add_event(
            EventTypes.TOOL_CALL_STARTED,
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "iteration": self.state.current_iteration,
                "arguments": tool_args,
            },
        )
        await self._publish_events_immediately()

        try:
            # Create Pydantic request model for MCP tool execution
            # Extract workspace_id from state (should be set from request)
            workspace_id = self.state.workspace_id or self.state.user_context_data.get(
                "workspace_id"
            )
            if not workspace_id:
                raise ValueError(
                    f"Missing workspace_id in workflow state for task {self.state.task_id}"
                )

            mcp_request = MCPToolRequest(
                tool_name=tool_name,
                tool_args=tool_args,
                server_instance_id=None,
                workspace_id=workspace_id,
                task_id=str(self.state.task_id),
                agent_id=UUID(self.state.agent_id) if self.state.agent_id else None,
                tools=self.state.agent_config.get("tools"),
                metadata=self._workflow_metadata or {},
                effective_policy=self.state.effective_policy,
            )

            result_obj = await workflow.execute_activity(
                Activities.EXECUTE_MCP_TOOL,
                args=[mcp_request],
                start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

            # Normalize result to a dict for robust access
            result_dict: dict[str, Any]
            if hasattr(result_obj, "model_dump") and callable(result_obj.model_dump):
                try:
                    result_dict = result_obj.model_dump()  # type: ignore[attr-defined]
                except Exception:
                    result_dict = {}
            elif isinstance(result_obj, dict):
                result_dict = result_obj
            else:
                result_dict = getattr(result_obj, "__dict__", {}) or {}

            # Extract fields with fallbacks
            success = bool(result_dict.get("success", getattr(result_obj, "success", True)))
            error_text = result_dict.get("error", getattr(result_obj, "error", None))
            # Prefer standard "result", fallback to "output", then stringify the whole object
            result_text = result_dict.get("result", getattr(result_obj, "result", None))
            if result_text is None:
                result_text = result_dict.get("output", getattr(result_obj, "output", ""))
            result_text = str(result_text) if result_text is not None else ""

            # Execution time may be named differently
            execution_time = result_dict.get(
                "execution_time", getattr(result_obj, "execution_time", None)
            ) or result_dict.get(
                "execution_time_seconds", getattr(result_obj, "execution_time_seconds", None)
            )

            # Failure path: surface the error to the LLM and emit ToolCallFailed
            # so the UI renders an actual error instead of "(no result data)".
            if not success:
                error_message = error_text or result_text or "Tool execution failed"
                workflow.logger.warning(f"Tool '{tool_name}' returned failure: {error_message}")
                self.state.messages.append(
                    Message(
                        role="tool",
                        content=f"Tool failed: {error_message}",
                        tool_call_id=tool_call.id,
                        name=tool_name,
                    )
                )
                self.event_manager.add_event(
                    EventTypes.TOOL_CALL_FAILED,
                    {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.id,
                        "error": error_message,
                        "arguments": tool_args,
                        "execution_time": execution_time,
                        "iteration": self.state.current_iteration,
                    },
                )
                await self._publish_events_immediately()
                return

            # Offload large outputs to MinIO (hybrid/dynamic strategy)
            result_text = await self._maybe_offload_output(result_text, tool_call.id)

            # Add tool result to conversation
            self.state.messages.append(
                Message(
                    role="tool",
                    content=result_text,
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            # Publish tool completion event
            self.event_manager.add_event(
                EventTypes.TOOL_CALL_COMPLETED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "success": success,
                    "iteration": self.state.current_iteration,
                    "result": result_text,
                    "arguments": tool_args,
                    "execution_time": execution_time,
                },
            )
            await self._publish_events_immediately()

            workflow.logger.info(f"MCP tool '{tool_name}' executed successfully")

        except Exception as e:
            workflow.logger.error(f"MCP tool call {tool_name} failed: {e}")

            # Add error message to conversation
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Tool execution failed: {e}",
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            # Publish tool failure event
            self.event_manager.add_event(
                EventTypes.TOOL_CALL_FAILED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "error": str(e),
                    "iteration": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()

    async def _execute_recall_history(self, tool_call: ToolCall) -> None:
        """Execute recall_history tool.

        If grep or tool_name are provided and history chunks exist in MinIO,
        searches MinIO first. Falls back to DB event log query.
        """
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        grep = tool_args.get("grep")
        tool_name_filter = tool_args.get("tool_name")

        # Try MinIO history search first if grep/tool_name provided and chunks exist
        strategy = ContextStrategy(self.state.context_strategy)
        if (
            (grep or tool_name_filter)
            and allows_history_preservation(strategy)
            and self.state.history_chunk_counter > 0
        ):
            try:
                search_result: SearchHistoryResult = await workflow.execute_activity(
                    Activities.SEARCH_HISTORY,
                    args=[
                        SearchHistoryRequest(
                            task_id=str(self.state.task_id),
                            workspace_id=str(self.state.workspace_id),
                            grep=grep,
                            tool_name=tool_name_filter,
                        )
                    ],
                    result_type=SearchHistoryResult,
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                if search_result.success and search_result.results:
                    self.state.messages.append(
                        Message(
                            role="tool",
                            content=f"[History search results]\n{search_result.results}",
                            tool_call_id=tool_call.id,
                            name="recall_history",
                        )
                    )
                    return
            except Exception as e:
                workflow.logger.warning(f"MinIO history search failed, falling back to DB: {e}")

        # Fall back to DB event log query
        request = RecallHistoryRequest(
            task_id=UUID(self.state.task_id),
            workspace_id=self.state.workspace_id,
            query=tool_args.get("query"),
            event_types=tool_args.get("event_types"),
            limit=tool_args.get("limit", 20),
            user_context_data=self.state.user_context_data,
        )

        try:
            result: RecallHistoryResult = await workflow.execute_activity(
                Activities.RECALL_HISTORY,
                args=[request],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Format events for the agent
            if result.events:
                content_parts = [result.summary, ""]
                for event in result.events:
                    content_parts.append(
                        f"[{event.get('created_at', '')}] "
                        f"{event.get('event_type', '')}: "
                        f"{json.dumps(event.get('data', {}), default=str)[:500]}"
                    )
                content = "\n".join(content_parts)
            else:
                content = "No events found for this task."

            self.state.messages.append(
                Message(
                    role="tool",
                    content=content,
                    tool_call_id=tool_call.id,
                    name="recall_history",
                )
            )
        except Exception as e:
            workflow.logger.error(f"Recall history failed: {e}")
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Failed to recall history: {e}",
                    tool_call_id=tool_call.id,
                    name="recall_history",
                )
            )

    async def _execute_read_tool_output(self, tool_call: ToolCall) -> None:
        """Execute read_tool_output tool to retrieve offloaded content from MinIO."""
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        output_id = tool_args.get("output_id", "")
        if not output_id:
            self.state.messages.append(
                Message(
                    role="tool",
                    content="Error: output_id is required.",
                    tool_call_id=tool_call.id,
                    name="read_tool_output",
                )
            )
            return

        try:
            read_result: ReadOutputResult = await workflow.execute_activity(
                Activities.READ_CONTEXT_OUTPUT,
                args=[
                    ReadOutputRequest(
                        task_id=str(self.state.task_id),
                        workspace_id=str(self.state.workspace_id),
                        output_id=output_id,
                        grep=tool_args.get("grep"),
                        head=tool_args.get("head"),
                        tail=tool_args.get("tail"),
                    )
                ],
                result_type=ReadOutputResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            content = (
                read_result.content
                if read_result.success
                else f"Error reading output: {read_result.error}"
            )
        except Exception as e:
            workflow.logger.error(f"read_tool_output failed: {e}")
            content = f"Failed to read output '{output_id}': {e}"

        self.state.messages.append(
            Message(
                role="tool",
                content=content,
                tool_call_id=tool_call.id,
                name="read_tool_output",
            )
        )

    async def _maybe_offload_output(self, content: str, output_id: str) -> str:
        """Offload large tool output to MinIO if strategy allows. Returns summary or original."""
        strategy = ContextStrategy(self.state.context_strategy)
        if not allows_output_offloading(strategy):
            return content
        if len(content) <= TOOL_OUTPUT_OFFLOAD_CHARS:
            return content

        try:
            store_result: StoreOutputResult = await workflow.execute_activity(
                Activities.STORE_CONTEXT_OUTPUT,
                args=[
                    StoreOutputRequest(
                        task_id=str(self.state.task_id),
                        workspace_id=str(self.state.workspace_id),
                        output_id=output_id,
                        content=content,
                    )
                ],
                result_type=StoreOutputResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            if store_result.success:
                return build_output_summary(content, output_id)
            # Fallback: keep full content if store failed
            workflow.logger.warning(f"Output offload failed for {output_id}: {store_result.error}")
            return content
        except Exception as e:
            # Fallback: MinIO failure doesn't break agent execution
            workflow.logger.warning(f"Output offload exception for {output_id}: {e}")
            return content

    async def _execute_load_openapi_tools(self, tool_call: ToolCall) -> None:
        """Reveal OpenAPI operation schemas by exact name (issue #115 — local).

        Mirrors `_execute_activate_tool_source` for the per-tool, name-based
        case: the LLM picks names from the catalog text already in its prompt
        and asks us to load their schemas. We dict-look up against
        `state.searchable_tool_pool` and append matched schemas (deduped) to
        `state.available_tools`. Names are recorded in
        `state.revealed_openapi_tools` so continue-as-new can replay them.
        """
        try:
            args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}

        requested = args.get("tool_names")
        if not isinstance(requested, list):
            requested = []
        requested = [str(n) for n in requested if n]

        if not self._disclosure_policy or not self.state.searchable_tool_pool:
            self.state.messages.append(
                Message(
                    role="tool",
                    content="Error: no searchable OpenAPI pool available.",
                    tool_call_id=tool_call.id,
                    name="load_tools",
                )
            )
            return

        pool = [ToolCandidate(**c) for c in self.state.searchable_tool_pool]
        ctx = DisclosureContext(
            model_name=str(self.state.agent_config.get("model_id", "")),
            context_window=self.state.context_window,
            iteration=self.state.current_iteration,
        )
        result = self._disclosure_policy.reveal(
            RevealRequest(tool_names=requested), pool, ctx
        )

        # Dedup against already-loaded tools by function name.
        existing_names = {
            (t.get("function", {}) or {}).get("name")
            for t in self.state.available_tools
            if t.get("type") == "function"
        }
        for schema in result.revealed:
            name = (schema.get("function", {}) or {}).get("name")
            if name and name not in existing_names:
                self.state.available_tools.append(schema)
                existing_names.add(name)

        revealed_set = set(self.state.revealed_openapi_tools)
        for name in result.matched_names:
            if name not in revealed_set:
                self.state.revealed_openapi_tools.append(name)
                revealed_set.add(name)

        self.state.messages.append(
            Message(
                role="tool",
                content=result.message
                or f"Loaded {len(result.matched_names)} OpenAPI operations.",
                tool_call_id=tool_call.id,
                name="load_tools",
            )
        )

        self.event_manager.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": "load_tools",
                "tool_call_id": tool_call.id,
                "matched_names": result.matched_names,
                "unknown_names": result.unknown_names,
                "iteration": self.state.current_iteration,
            },
        )

    async def _execute_activate_tool_source(self, tool_call: ToolCall) -> None:
        """Activate a tool source (DYNAMIC mode) — load full definitions into context."""
        try:
            args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}

        source_name = args.get("source_name", "")

        if not self._tool_catalog:
            self.state.messages.append(
                Message(
                    role="tool",
                    content="Error: tool catalog not available (not in dynamic mode).",
                    tool_call_id=tool_call.id,
                    name="activate_tool_source",
                )
            )
            return

        new_tools = self._tool_catalog.activate(source_name)
        if new_tools:
            self.state.available_tools.extend(new_tools)
            # Track activated sources for continue-as-new
            activated_sources = getattr(self.state, "activated_tool_sources", []) or []
            if source_name not in activated_sources:
                activated_sources.append(source_name)
                # Store back — ContinueAsNewState carries this
                if hasattr(self.state, "activated_tool_sources"):
                    self.state.activated_tool_sources = activated_sources

            tool_names = [t.get("function", {}).get("name", "?") for t in new_tools]
            result_text = (
                f"Activated '{source_name}' with {len(new_tools)} tools: {', '.join(tool_names)}"
            )
        else:
            result_text = f"Tool source '{source_name}' not found or has no tools."

        self.state.messages.append(
            Message(
                role="tool",
                content=result_text,
                tool_call_id=tool_call.id,
                name="activate_tool_source",
            )
        )

        self.event_manager.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": "activate_tool_source",
                "tool_call_id": tool_call.id,
                "source_name": source_name,
                "tools_loaded": len(new_tools),
                "iteration": self.state.current_iteration,
            },
        )

    async def _execute_skill_activation(self, tool_call: ToolCall) -> None:
        """Execute skill activation locally (no Temporal activity needed)."""
        try:
            args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}

        skill_name = args.get("skill_name", "")

        if not self._skill_tool:
            result_text = "No skills available."
        else:
            result = await self._skill_tool.execute(**args)
            result_text = result.get("result", "")

        self.state.messages.append(
            Message(
                role="tool",
                content=result_text,
                tool_call_id=tool_call.id,
                name="activate_skill",
            )
        )

        if skill_name and skill_name not in self.state.activated_skills:
            self.state.activated_skills.append(skill_name)

        self.event_manager.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": "activate_skill",
                "tool_call_id": tool_call.id,
                "skill_name": skill_name,
                "iteration": self.state.current_iteration,
            },
        )

    async def _execute_skill_script(self, tool_call: ToolCall) -> None:
        """Execute a skill-bundled script via MCP Manager sandbox."""
        try:
            args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}

        skill_name = args.get("skill_name", "")
        script_name = args.get("script_name", "")
        script_args = args.get("args", "")
        artifact_paths = args.get("artifact_paths") or []
        if not isinstance(artifact_paths, list):
            artifact_paths = []

        # Validate skill is activated
        if skill_name not in self.state.activated_skills:
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Error: skill '{skill_name}' has not been activated. Call activate_skill first.",
                    tool_call_id=tool_call.id,
                    name="run_skill_script",
                )
            )
            return

        # Fetch script content from skill package via existing activity
        skill_config = next(
            (s for s in self.state.agent_config.get("skills", []) if s.get("name") == skill_name),
            None,
        )
        if not skill_config:
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Error: skill '{skill_name}' not found in agent config.",
                    tool_call_id=tool_call.id,
                    name="run_skill_script",
                )
            )
            return

        # Try to fetch script from skill package (S3)
        script_content = None
        skill_id = skill_config.get("id")
        if skill_id:
            try:
                file_result = await workflow.execute_activity(
                    Activities.RESOLVE_SKILL_FILE,
                    args=[
                        SkillFileRequest(
                            skill_id=UUID(skill_id),
                            file_path=script_name,
                            workspace_id=self.state.workspace_id,
                            user_context_data=self.state.user_context_data,
                        )
                    ],
                    result_type=SkillFileResult,
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                if file_result.success:
                    script_content = file_result.content_text
                    if not script_content and file_result.content:
                        script_content = file_result.content.decode("utf-8")
            except Exception as e:
                workflow.logger.warning(f"Could not fetch script from S3: {e}")

        if not script_content:
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Error: script '{script_name}' not found in skill '{skill_name}'.",
                    tool_call_id=tool_call.id,
                    name="run_skill_script",
                )
            )
            return

        # Execute via MCP Manager sandbox. The activity layer owns scoping
        # to the current task — workflow code stays oblivious to sandbox
        # internals.
        script_args_list = [script_args] if script_args else []
        result = await workflow.execute_activity(
            Activities.EXECUTE_SKILL_SCRIPT,
            args=[
                ExecuteSkillScriptRequest(
                    script_content=script_content,
                    script_name=script_name,
                    args=script_args_list,
                    artifact_paths=[str(path) for path in artifact_paths],
                    timeout_seconds=1800,
                    workspace_id=str(self.state.workspace_id) if self.state.workspace_id else None,
                    task_id=str(self.state.task_id) if self.state.task_id else None,
                )
            ],
            result_type=ExecuteSkillScriptResult,
            start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Build result message
        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"STDERR: {result.stderr}")
        if result.exit_code != 0:
            output_parts.append(f"Exit code: {result.exit_code}")
        if result.artifacts:
            output_parts.append(f"Artifacts: {json.dumps(result.artifacts, ensure_ascii=False)}")
        content = "\n".join(output_parts) or "(no output)"

        # Offload large script outputs to MinIO (hybrid/dynamic strategy)
        content = await self._maybe_offload_output(content, f"script_{tool_call.id}")

        self.state.messages.append(
            Message(
                role="tool",
                content=content,
                tool_call_id=tool_call.id,
                name="run_skill_script",
            )
        )

        self.event_manager.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": "run_skill_script",
                "tool_call_id": tool_call.id,
                "skill_name": skill_name,
                "script_name": script_name,
                "exit_code": result.exit_code,
                "iteration": self.state.current_iteration,
            },
        )

    async def _execute_agent_delegation(self, tool_call: ToolCall) -> None:
        """Delegate to another agent via Temporal child workflow.

        Instead of routing through execute_mcp_tool_activity (which polls),
        starts a child workflow directly and awaits its result. This is
        efficient (no polling), durable (survives worker crashes), and
        supports cancellation propagation.
        """
        tool_name = tool_call.function["name"]
        agent_info = self._agent_tool_registry[tool_name]
        agent_id = agent_info["agent_id"]
        agent_name = agent_info["agent_name"]

        # Parse the message argument
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        message = tool_args.get("message", "")

        self.event_manager.add_event(
            EventTypes.AGENT_DELEGATION_STARTED,
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "target_agent_id": agent_id,
                "target_agent_name": agent_name,
                "iteration": self.state.current_iteration,
                "message": message[:200],
            },
        )
        await self._publish_events_immediately()

        try:
            # Create a task record in DB for the child agent
            create_task_request = CreateDelegationTaskRequest(
                parent_agent_id=self.state.agent_id,
                parent_task_id=self.state.task_id,
                target_agent_id=agent_id,
                target_agent_name=agent_name,
                message=message,
                user_id=self.state.user_id,
                workspace_id=self.state.workspace_id,
            )
            create_task_result: CreateDelegationTaskResult = await workflow.execute_activity(
                Activities.CREATE_DELEGATION_TASK,
                args=[create_task_request],
                result_type=CreateDelegationTaskResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

            if create_task_result.status != "created" or not create_task_result.task_id:
                raise ApplicationError(
                    f"Failed to create delegation task: {create_task_result.error}"
                )

            child_task_id = create_task_result.task_id

            # Build child workflow request with its own task_id
            child_request = AgentExecutionRequest(
                task_id=child_task_id,
                agent_id=UUID(agent_id),
                user_id=self.state.user_id,
                workspace_id=self.state.workspace_id,
                task_query=message,
                max_reasoning_iterations=MAX_ITERATIONS,
                workflow_metadata={
                    "source": "agent_delegation",
                    "parent_execution_id": self.state.execution_id,
                    "parent_agent_id": self.state.agent_id,
                    "parent_task_id": self.state.task_id,
                },
                effective_policy=self.state.effective_policy,
            )

            # Start child workflow and await result
            # - execution_timeout: caps total child runtime
            # - parent_close_policy: TERMINATE ensures child is cancelled
            #   if the parent workflow is cancelled or completed
            child_workflow_id = f"delegation-{self.state.execution_id}-{tool_call.id}"
            child_result: AgentExecutionResult = await workflow.execute_child_workflow(
                AgentExecutionWorkflow.run,
                args=[child_request],
                id=child_workflow_id,
                task_queue="agent-tasks",
                execution_timeout=DELEGATION_TIMEOUT,
                parent_close_policy=ParentClosePolicy.TERMINATE,
            )

            # Build a structured envelope for the parent's LLM. Same shape
            # for success and failure so the parent can branch on `status`.
            # `final_response` is the child's own narrative; `task_id` lets
            # the parent call get_task_summary later for the full record.
            if child_result.success:
                envelope: dict[str, Any] = {
                    "status": "completed",
                    "agent": agent_name,
                    "task_id": str(child_task_id),
                    "final_response": child_result.final_response
                    or "(Agent completed without response)",
                    "iterations": child_result.reasoning_iterations_used,
                    "cost_usd": float(child_result.total_cost),
                }
            else:
                envelope = {
                    "status": "failed",
                    "agent": agent_name,
                    "task_id": str(child_task_id),
                    "error": child_result.error_message or "(Agent failed without details)",
                    "iterations": child_result.reasoning_iterations_used,
                    "cost_usd": float(child_result.total_cost),
                }

            self.state.messages.append(
                Message(
                    role="tool",
                    content=json.dumps(envelope),
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            self.event_manager.add_event(
                EventTypes.AGENT_DELEGATION_COMPLETED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "target_agent_id": agent_id,
                    "target_agent_name": agent_name,
                    "child_task_id": str(child_task_id),
                    "success": child_result.success,
                    "iteration": self.state.current_iteration,
                    "child_iterations": child_result.reasoning_iterations_used,
                    "child_cost": float(child_result.total_cost),
                },
            )
            await self._publish_events_immediately()

            # Account for child's cost in parent budget
            if child_result.total_cost > 0:
                self.budget_tracker.add_cost(child_result.total_cost)

            workflow.logger.info(
                f"Agent delegation to '{agent_name}' completed "
                f"(success={child_result.success}, cost=${child_result.total_cost:.4f})"
            )

        except Exception as e:
            # Surface the failure to the parent's LLM as a tool message and
            # continue. Re-raising here would propagate out of asyncio.gather
            # and abort sibling delegations — wrong semantics for fan-out
            # where each child's success/failure should be independent.
            workflow.logger.error(f"Agent delegation to '{agent_name}' failed: {e}", exc_info=True)

            error_payload = {
                "status": "failed",
                "agent": agent_name,
                "error": str(e),
            }
            self.state.messages.append(
                Message(
                    role="tool",
                    content=json.dumps(error_payload),
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            self.event_manager.add_event(
                EventTypes.AGENT_DELEGATION_FAILED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "target_agent_id": agent_id,
                    "target_agent_name": agent_name,
                    "error": str(e),
                    "iteration": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()

    async def _compact_context_if_needed(self) -> bool:
        """Check context usage and compact if threshold exceeded.

        Uses the head-and-tail strategy:
        1. Keep system prompt (head)
        2. Summarize middle messages via LLM
        3. Keep recent messages (tail)
        4. Validate tool pairs aren't broken

        Returns True if compaction was performed.
        """
        if not self.context_manager or not self.context_manager.needs_compaction():
            return False

        workflow.logger.info(
            f"Context compaction triggered at {self.context_manager.get_usage_ratio():.1%} usage"
        )

        # Convert messages to dict for boundary finding
        messages_dict = [
            MessageBuilder.normalize_message_dict(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                    "tool_calls": msg.tool_calls,
                }
            )
            for msg in self.state.messages
        ]

        # Find safe compaction boundary
        boundary = find_compaction_boundary(messages_dict, keep_recent=4)
        if boundary <= 1:
            workflow.logger.warning("No safe compaction boundary found, skipping")
            return False

        # Messages to compact: everything between system prompt and boundary
        messages_to_compact = messages_dict[1:boundary]
        if not messages_to_compact:
            return False

        # Preserve full history in MinIO before compaction (best-effort)
        strategy = ContextStrategy(self.state.context_strategy)
        if allows_history_preservation(strategy):
            try:
                chunk_index = self.state.history_chunk_counter
                store_hist_result: StoreHistoryResult = await workflow.execute_activity(
                    Activities.STORE_HISTORY_CHUNK,
                    args=[
                        StoreHistoryRequest(
                            task_id=str(self.state.task_id),
                            workspace_id=str(self.state.workspace_id),
                            chunk_index=chunk_index,
                            messages=messages_to_compact,
                        )
                    ],
                    result_type=StoreHistoryResult,
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                if store_hist_result.success:
                    self.state.history_chunk_counter += 1
                    workflow.logger.info(f"Stored history chunk {chunk_index} before compaction")
                else:
                    workflow.logger.warning(
                        f"History chunk store failed: {store_hist_result.error}"
                    )
            except Exception as e:
                workflow.logger.warning(f"History preservation failed (non-blocking): {e}")

        # Call compaction activity
        try:
            compact_request = CompactMessagesRequest(
                messages_to_compact=messages_to_compact,
                model_id=self.state.agent_config.get("model_id"),
                workspace_id=self.state.workspace_id,
                user_context_data=self.state.user_context_data,
                resolved_model=self.state.resolved_model,
            )

            result: CompactMessagesResult = await workflow.execute_activity(
                Activities.COMPACT_MESSAGES,
                args=[compact_request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Rebuild message list: system prompt + summary + kept recent messages
            system_msg = self.state.messages[0]
            recent_messages = list(self.state.messages[boundary:])

            summary_msg = Message(
                role="user",
                content=f"[Previous conversation summary]\n{result.summary}",
            )

            self.state.messages = [system_msg, summary_msg, *recent_messages]

            # Validate tool pairs in new message list
            new_messages_dict = [
                MessageBuilder.normalize_message_dict(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                        "name": msg.name,
                        "tool_calls": msg.tool_calls,
                    }
                )
                for msg in self.state.messages
            ]
            if not validate_tool_pairs(new_messages_dict):
                workflow.logger.error("Tool pair validation failed after compaction!")
                # Repair: drop orphaned tool results
                tool_use_ids: set[str] = set()
                for msg in self.state.messages:
                    if msg.role == "assistant" and msg.tool_calls:
                        for tc in msg.tool_calls:
                            if isinstance(tc, dict) and tc.get("id"):
                                tool_use_ids.add(tc["id"])
                self.state.messages = [
                    msg
                    for msg in self.state.messages
                    if not (msg.role == "tool" and msg.tool_call_id not in tool_use_ids)
                ]

            self.context_manager.mark_compacted()

            # Publish compaction event
            self.event_manager.add_event(
                EventTypes.CONTEXT_COMPACTED,
                {
                    "iteration": self.state.current_iteration,
                    "messages_compacted": result.original_message_count,
                    "tokens_saved": result.estimated_tokens_saved,
                    "compaction_number": self.context_manager.compaction_count,
                    "messages_remaining": len(self.state.messages),
                },
            )
            await self._publish_events_immediately()

            workflow.logger.info(
                f"Compacted {result.original_message_count} messages, "
                f"~{result.estimated_tokens_saved} tokens saved, "
                f"{len(self.state.messages)} messages remaining"
            )
            return True

        except Exception as e:
            workflow.logger.error(f"Context compaction failed: {e}")
            return False

    async def _check_budget_status(self) -> None:
        """Check budget status and send warnings if needed."""
        if self.budget_tracker.should_warn():
            self.event_manager.add_event(
                EventTypes.BUDGET_WARNING,
                {
                    "usage_percentage": self.budget_tracker.get_usage_percentage(),
                    "cost": serialize_money(self.budget_tracker.cost),
                    "limit": serialize_money(self.budget_tracker.budget_limit),
                    "message": self.budget_tracker.get_warning_message(),
                },
            )
            await self._publish_events_immediately()
            self.budget_tracker.mark_warning_sent()

        if self.budget_tracker.is_exceeded():
            self.event_manager.add_event(
                EventTypes.BUDGET_EXCEEDED,
                {
                    "cost": serialize_money(self.budget_tracker.cost),
                    "limit": serialize_money(self.budget_tracker.budget_limit),
                    "message": self.budget_tracker.get_exceeded_message(),
                },
            )
            await self._publish_events_immediately()

    async def _publish_events(self) -> None:
        """Publish pending events using Pydantic models."""
        events = self.event_manager.get_events()
        if not events:
            return

        try:
            events_json = [json.dumps(event) for event in events]

            # Create Pydantic request model for event publishing
            events_request = WorkflowEventsRequest(
                events_json=events_json,
                workspace_id=self.state.workspace_id,
                user_id=self.state.user_id,
            )

            await workflow.execute_activity(
                Activities.PUBLISH_WORKFLOW_EVENTS,
                args=[events_request],
                start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=EVENT_PUBLISH_RETRY_ATTEMPTS),
            )

            self.event_manager.clear_events()

        except Exception as e:
            workflow.logger.warning(f"Failed to publish events: {e}")

    async def _publish_events_immediately(self) -> None:
        """Publish events immediately as they occur - fire and forget using Pydantic models."""
        pending_events = self.event_manager.get_pending_events()

        # Only proceed if we have events to publish
        if not pending_events:
            return

        # Clear pending events immediately since we're not waiting for confirmation
        self.event_manager.clear_pending_events()

        events_json = [json.dumps(event) for event in pending_events]

        # Fire and forget - publish async without waiting for result
        workflow.logger.debug(f"Publishing {len(events_json)} events immediately")

        # Create Pydantic request model for event publishing
        events_request = WorkflowEventsRequest(
            events_json=events_json,
            workspace_id=self.state.workspace_id,
            user_id=self.state.user_id,
        )

        # Start the activity but don't await it (fire and forget)
        await workflow.execute_activity(
            Activities.PUBLISH_WORKFLOW_EVENTS,
            args=[events_request],
            start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),  # Single attempt only
        )

    async def _finalize_execution(self, result: dict[str, Any]) -> AgentExecutionResult:
        """Finalize workflow execution and return result."""
        workflow.logger.info("Finalizing workflow execution")

        # Determine final status.
        # If task_complete was already called, the task succeeded regardless of
        # follow-up message processing failures.
        if self._completion_event_published or self.state.success:
            self.state.status = ExecutionStatus.COMPLETED
            self.state.success = True
        else:
            if self.state.status != ExecutionStatus.BLOCKED:
                self.state.status = ExecutionStatus.FAILED

        # Only publish completion/failure event if not already published at task_complete
        if not self._completion_event_published:
            event_type = (
                EventTypes.WORKFLOW_COMPLETED if self.state.success else EventTypes.WORKFLOW_FAILED
            )
            self.event_manager.add_event(
                event_type,
                {
                    "success": self.state.success,
                    "iterations_completed": self.state.current_iteration,
                    "total_cost": serialize_money(self.budget_tracker.cost),
                    "final_response": self.state.final_response,
                    "status": self.state.status,
                    "blocked_reason": self.state.blocked_reason,
                },
            )
            await self._publish_events_immediately()

        # Update task status in the database.
        # If task_complete already set status to "completed", don't downgrade it.
        if self._completion_event_published:
            final_status = "completed"
        elif self.state.success:
            final_status = "completed"
        elif self.state.status == ExecutionStatus.BLOCKED:
            final_status = "blocked"
        else:
            final_status = "failed"
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
                UpdateTaskStatusRequest(
                    task_id=self.state.task_id,
                    status=final_status,
                    result=json.dumps({"response": self.state.final_response})
                    if self.state.final_response
                    else None,
                    error_message=self.state.blocked_reason if final_status == "blocked" else None,
                    workspace_id=self.state.workspace_id,
                    total_cost=serialize_money(self.budget_tracker.cost)
                    if self.budget_tracker
                    else "0",
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

        try:
            await workflow.execute_activity(
                Activities.CLEANUP_SANDBOX_WORKFLOW,
                args=[workflow.info().workflow_id],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as e:
            workflow.logger.warning(f"Sandbox workflow cleanup failed: {e}")

        # Return result - convert messages to dict format for response
        conversation_history: list[dict[str, Any]] = []
        for msg in self.state.messages:
            msg_dict: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.name:
                msg_dict["name"] = msg.name
            if msg.tool_calls:
                msg_dict["tool_calls"] = msg.tool_calls
            conversation_history.append(msg_dict)

        return AgentExecutionResult(
            task_id=UUID(self.state.task_id),
            agent_id=UUID(self.state.agent_id),
            success=self.state.success,
            final_response=self.state.final_response,
            total_cost=serialize_money(self.budget_tracker.cost) if self.budget_tracker else "0",
            reasoning_iterations_used=self.state.current_iteration,
            conversation_history=conversation_history,
        )

    async def _handle_workflow_error(self, error: Exception) -> None:
        """Handle workflow-level errors."""
        error_details = self._extract_temporal_error_details(error)
        user_message = self._get_user_facing_error(error)

        if self.event_manager:
            self.event_manager.add_event(
                EventTypes.WORKFLOW_FAILED,
                {
                    "error": user_message,
                    "error_type": self._get_user_facing_error_type(error),
                    "iterations_completed": self.state.current_iteration,
                    "status": self.state.status,
                    "blocked_reason": self.state.blocked_reason,
                },
            )
            await self._publish_events_immediately()
        workflow.logger.error(f"Workflow failed: {error_details}")

        # Update task status to failed
        if self.state and self.state.task_id:
            status = "blocked" if self.state.status == ExecutionStatus.BLOCKED else "failed"
            await workflow.execute_activity(
                Activities.UPDATE_TASK_STATUS,
                args=[
                    UpdateTaskStatusRequest(
                        task_id=self.state.task_id,
                        status=status,
                        error_message=self.state.blocked_reason or error_details,
                        workspace_id=self.state.workspace_id,
                    )
                ],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

    @staticmethod
    def _get_user_facing_error(error: Exception) -> str:
        """Return a short, user-friendly error message (no stack traces)."""
        msg = str(error).lower()
        cause_msg = ""
        if isinstance(error, ActivityError) and error.cause:
            cause_msg = str(error.cause).lower()

        activity_name = ""
        if isinstance(error, ActivityError) and error.activity_type:
            activity_name = error.activity_type.lower()

        combined = f"{msg} {cause_msg} {activity_name}"

        if "model_id" in combined and ("none" in combined or "valid string" in combined):
            return "No model is configured for this agent. Please assign a model in agent settings."
        if "build_agent_config" in combined:
            return "Agent configuration error. Please check the agent settings."
        if "call_llm" in combined:
            if "auth" in combined or "api_key" in combined or "unauthorized" in combined:
                return "Authentication failed with the LLM provider. Please check your API key."
            if "rate_limit" in combined or "429" in combined:
                return "Rate limit exceeded. Please try again in a moment."
            if "timeout" in combined:
                return "The AI model request timed out. Please try again."
            if "deprecated" in combined:
                return "The configured model has been deprecated by the provider. Please select a different model."
            if "not found" in combined or "notfounderror" in combined or "404" in combined:
                return "The configured model was not found. Please check the model name or select a different one."
            return "Failed to get a response from the AI model."
        if "execute_mcp_tool" in combined or "tool_execution" in combined:
            return "A tool execution failed during the task."
        if "budget" in combined:
            return "Task budget has been exceeded."
        if "compact_messages" in combined:
            return "Failed to manage conversation context. Please try again."

        # Generic fallback — activity name only, no internals
        if isinstance(error, ActivityError) and error.activity_type:
            activity = error.activity_type.replace("_activity", "").replace("_", " ")
            return f"Task failed during {activity}. Please try again."

        return "An unexpected error occurred. Please try again."

    @staticmethod
    def _get_user_facing_error_type(error: Exception) -> str:
        """Return a human-readable error category instead of raw Python class names."""
        combined = str(error).lower()
        if isinstance(error, ActivityError):
            if error.cause:
                combined += " " + str(error.cause).lower()

        if "auth" in combined or "api_key" in combined or "unauthorized" in combined:
            return "AuthenticationError"
        if "rate_limit" in combined or "429" in combined:
            return "RateLimitError"
        if "deprecated" in combined:
            return "ModelDeprecated"
        if "not found" in combined or "notfounderror" in combined or "404" in combined:
            return "ModelNotFound"
        if "timeout" in combined:
            return "TimeoutError"
        if "budget" in combined or "quota" in combined:
            return "BudgetExceeded"
        if "model_id" in combined and "none" in combined:
            return "ConfigurationError"
        return "Error"

    def _extract_temporal_error_details(self, error: Exception) -> str:
        """Extract actionable details from Temporal errors (Activity/ApplicationError)."""
        if isinstance(error, ActivityError):
            parts = [str(error)]
            if error.activity_type:
                parts.append(f"activity={error.activity_type}")
            if error.retry_state:
                parts.append(f"retry_state={error.retry_state}")

            cause = error.cause
            if cause is not None:
                parts.append(f"cause={cause!s}")
                if isinstance(cause, ApplicationError):
                    if cause.type:
                        parts.append(f"cause_type={cause.type}")
                    if cause.details:
                        parts.append(f"cause_details={cause.details}")
            return " | ".join(parts)

        if isinstance(error, ApplicationError):
            parts = [str(error)]
            if error.type:
                parts.append(f"type={error.type}")
            if error.details:
                parts.append(f"details={error.details}")
            return " | ".join(parts)

        return str(error)

    def _build_goal_from_request(self, request: AgentExecutionRequest) -> AgentGoal:
        """Build goal from execution request."""
        return AgentGoal(
            id=str(request.task_id),
            description=request.task_query,
            success_criteria=request.task_parameters.get(
                "success_criteria", ["Task completed successfully"]
            ),
            max_iterations=request.task_parameters.get(
                "max_iterations", request.max_reasoning_iterations
            ),
            requires_human_approval=request.requires_human_approval,
            context=request.task_parameters,
        )

    # Query methods for external inspection
    @workflow.query
    def get_workflow_events(self) -> list[dict[str, Any]]:
        """Get all workflow events."""
        return self.event_manager.get_events() if self.event_manager else []

    @workflow.query
    def get_latest_events(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get latest workflow events."""
        return self.event_manager.get_latest_events(limit) if self.event_manager else []

    @workflow.query
    def get_current_state(self) -> dict[str, Any]:
        """Get current workflow state."""
        return {
            "status": self.state.status,
            "current_iteration": self.state.current_iteration,
            "success": self.state.success,
            "cost": serialize_money(self.budget_tracker.cost) if self.budget_tracker else "0",
            "budget_remaining": (
                serialize_money(self.budget_tracker.get_remaining()) if self.budget_tracker else "0"
            ),
            "paused": self._paused,
            "pause_reason": self._pause_reason,
            "blocked_reason": self.state.blocked_reason,
            "pending_escalations": {
                eid: {
                    "tool_name": e.tool_name,
                    "tool_call_id": e.tool_call_id,
                    "resolved": e.resolved,
                }
                for eid, e in self._pending_escalations.items()
            },
            "context": self.context_manager.get_status() if self.context_manager else None,
        }

    def _tool_requires_approval(self, tool_name: str) -> bool:
        """Check agent tools for per-tool user confirmation requirement.

        Checks both:
        - Top-level requires_user_confirmation on the tool config (code/agent tools)
        - Per-tool requires_user_confirmation in allowed_tools (MCP tools)
        """
        try:
            tools = (self.state.agent_config or {}).get("tools") or []
        except Exception:
            tools = []

        for tool_config in tools:
            if not isinstance(tool_config, dict):
                continue

            settings = tool_config.get("settings", {}) or {}

            # Direct match by name (code tools, agent tools)
            if tool_config.get("name") == tool_name:
                if isinstance(settings, dict) and bool(
                    settings.get("requires_user_confirmation", False)
                ):
                    return True

            # MCP tools: check per-tool approval in allowed_tools
            if tool_config.get("type") == "mcp":
                allowed_tools = (
                    settings.get("allowed_tools") if isinstance(settings, dict) else None
                )
                if isinstance(allowed_tools, list):
                    for at in allowed_tools:
                        if isinstance(at, dict) and at.get("tool_name") == tool_name:
                            if bool(at.get("requires_user_confirmation", False)):
                                return True
                elif isinstance(allowed_tools, dict):
                    # Dict format: {tool_name: {requires_user_confirmation: bool}}
                    tool_settings = allowed_tools.get(tool_name)
                    if isinstance(tool_settings, dict) and bool(
                        tool_settings.get("requires_user_confirmation", False)
                    ):
                        return True

        return False
