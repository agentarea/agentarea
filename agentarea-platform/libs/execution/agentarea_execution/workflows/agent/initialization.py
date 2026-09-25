"""Starting a run: state, agent configuration, model and tools."""

from typing import Any, cast

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_agents_sdk.skills import SkillActivationTool, SkillCatalogBuilder, SkillEntry
    from agentarea_agents_sdk.tools.disclosure import DisclosureContext, NamedLookupPolicy
    from agentarea_agents_sdk.tools.tool_catalog import ToolCatalog
    from agentarea_agents_sdk.tools.tool_provider import (
        AgentToolProvider,
        BuiltinToolProvider,
        CodeToolProvider,
        MCPToolProvider,
    )
    from agentarea_common.money import serialize_money

    from ...interaction import resolve_interaction_capabilities
    from ..context_manager import ContextWindowManager
    from ..context_strategy import (
        allows_output_offloading,
        allows_tool_progressive_disclosure,
        resolve_context_strategy,
    )
    from ..helpers import (
        BudgetTracker,
        EventManager,
        StateValidator,
        filter_disclosed_tools,
        resolve_effective_budget,
    )
    from ..models import AgentGoal

from ...models import (
    AgentConfigRequest,
    AgentConfigResult,
    AgentExecutionRequest,
    DiscoverToolProvidersResult,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    ToolDiscoveryResult,
)
from ..constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import make_retry_policy
from .builtin_tools import (
    completion_tool_schema,
    read_tool_output_tool_schema,
    recall_history_tool_schema,
    request_user_input_tool_schema,
)
from .continue_as_new import ContinueAsNewMixin
from .delegation import DelegationMixin
from .patches import INTERACTION_CONTRACT_PATCH


class InitializationMixin(DelegationMixin, ContinueAsNewMixin):
    """Starting a run: state, agent configuration, model and tools."""

    async def _initialize_workflow(self, request: AgentExecutionRequest) -> None:
        """Initialize workflow state and dependencies."""
        workflow.logger.info(f"Initializing workflow for agent {request.agent_id}")
        self._interaction_contract_enabled = workflow.patched(INTERACTION_CONTRACT_PATCH)

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
        # Single source of truth: the loop-level PEP (BudgetTracker) enforces the
        # same ceiling as the call-level PEP (CostBudgetGuard) — tightest wins.
        self.state.budget_usd = resolve_effective_budget(
            request.budget_usd, request.effective_policy
        )
        self.state.effective_policy = request.effective_policy
        self._workflow_metadata = dict(request.workflow_metadata or {})

        # Initialize helpers
        self.event_manager = EventManager(
            task_id=self.state.task_id,
            agent_id=self.state.agent_id,
            execution_id=self.state.execution_id,
            workspace_id=self.state.workspace_id,
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
            agent_id=UUID(self.state.agent_id),
            user_context_data=self.state.user_context_data,
            execution_context=self._workflow_metadata,
            task_id=UUID(self.state.task_id),
            task_parameters=self.state.goal.context if self.state.goal else {},
        )
        agent_config_result: AgentConfigResult = await workflow.execute_activity(
            Activities.BUILD_AGENT_CONFIG,
            args=[agent_config_request],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )

        # Convert result to dict for state storage (supports Pydantic BaseModel or plain dict)
        try:
            self.state.agent_config = agent_config_result.model_dump()
        except AttributeError:
            self.state.agent_config = dict(agent_config_result)

        if self.state.agent_config.get("execution_context") is not None:
            self._workflow_metadata = dict(self.state.agent_config["execution_context"])

        if self._interaction_contract_enabled:
            self.state.interaction_capabilities = resolve_interaction_capabilities(
                self.state.goal.context if self.state.goal else {},
                self._workflow_metadata,
                bool(self.state.agent_config.get("a2ui_enabled", False)),
            )

        self._events.add_event(
            EventTypes.RUNTIME_DISCOVERED,
            dict(self.state.agent_config.get("runtime_event_data") or {}),
        )
        await self._publish_events_immediately()

        # Store context window in state and initialize context manager
        context_window = self.state.agent_config.get("context_window")
        if (
            isinstance(context_window, bool)
            or not isinstance(context_window, int)
            or context_window <= 0
        ):
            raise ApplicationError(
                "agent configuration has no valid ModelSpec context_window",
                type="InvalidExecutionSnapshot",
                non_retryable=True,
            )
        self.state.context_window = context_window
        self.context_manager = ContextWindowManager(self.state.context_window)

        # Resolve model info once and cache in state to avoid per-call DB lookups
        model_id = self.state.agent_config.get("model_id")
        if model_id:
            try:
                resolve_model_request = ResolveModelRequest(
                    user_context_data=self.state.user_context_data,
                    model_id=model_id,
                    workspace_id=self.state.workspace_id,
                    user_id=self.state.user_id,
                )
                self.state.resolved_model = await workflow.execute_activity(
                    Activities.RESOLVE_MODEL,
                    args=[resolve_model_request],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
                )
                workflow.logger.info(
                    "Model resolved and cached: "
                    f"{self.state.resolved_model.get('model_name') if self.state.resolved_model else None}"
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
            agent_id=UUID(self.state.agent_id),
            user_context_data=self.state.user_context_data,
            tools=self.state.agent_config.get("tools"),
        )

        if allows_tool_progressive_disclosure(strategy):
            # DYNAMIC mode: discover providers, build catalog, inject only catalog + activate tool
            providers_result: DiscoverToolProvidersResult = await workflow.execute_activity(
                Activities.DISCOVER_TOOL_PROVIDERS,
                args=[tools_request],
                result_type=DiscoverToolProvidersResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
            )

            self.state.mcp_tool_routes = dict(providers_result.mcp_tool_routes)

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
            # STATIC/HYBRID mode: load all tools upfront (current behavior).
            # `result_type` is required for Temporal to deserialize the
            # activity result into the Pydantic model — otherwise the workflow
            # receives a plain dict and `searchable_entries` is silently dropped.
            tools_result: ToolDiscoveryResult = await workflow.execute_activity(
                Activities.DISCOVER_AVAILABLE_TOOLS,
                args=[tools_request],
                result_type=ToolDiscoveryResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
            )

            self.state.mcp_tool_routes = dict(tools_result.mcp_tool_routes)

            # Normalize tools to list[dict] for state storage, accepting multiple shapes
            available_tools: list[dict[str, Any]] = []
            try:
                tools_list = tools_result.tools  # Expected ToolDiscoveryResult
            except AttributeError:
                tools_list = tools_result  # Fallback: activity returned a raw list

            for tool in tools_list or []:
                try:
                    available_tools.append(cast(Any, tool).model_dump())  # Pydantic ToolDefinition
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
        completion_tool_definition = completion_tool_schema()
        available_tools = [
            t
            for t in available_tools
            if (t.get("function", {}).get("name") if t.get("type") == "function" else t.get("name"))
            not in {"completion", "task_complete"}
        ]
        available_tools.insert(0, completion_tool_definition)

        # request_user_input — pause the workflow until the user provides a reply.
        available_tools.insert(1, request_user_input_tool_schema())
        if self._interaction_contract_enabled:
            completion_tool_definition["function"]["parameters"]["properties"]["outcome"] = {
                "type": "string",
                "enum": ["completed", "blocked"],
                "description": (
                    "Use blocked only for an actual unmet prerequisite after attempting "
                    "available autonomous alternatives. Explain what is missing in result. "
                    "Unavailable questions alone are not a reason to stop."
                ),
            }
            available_tools[1]["function"]["parameters"]["properties"]["surface_id"] = {
                "type": "string",
                "description": (
                    "Bind required non-secret answers to an already emitted A2UI surface. "
                    "Action context keys must match question IDs. Omit for native input forms."
                ),
            }
            if not self._questions_available:
                available_tools = [
                    tool
                    for tool in available_tools
                    if (tool.get("function") or {}).get("name") != "request_user_input"
                ]

        # recall_history — query past execution context
        available_tools.append(recall_history_tool_schema())

        # Inject read_tool_output for retrieving offloaded large outputs (hybrid/dynamic)
        if allows_output_offloading(strategy):
            available_tools.append(read_tool_output_tool_schema())

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

        # Disclosure is a PDP decision: never offer the model a tool the gate
        # would reject (same policy, one decision, both ends).
        disclosed = filter_disclosed_tools(
            self.state.effective_policy, available_tools, self.state.mcp_tool_routes
        )
        withheld = len(available_tools) - len(disclosed)
        if withheld:
            workflow.logger.info(f"Policy withheld {withheld} tool(s) from the model")
        self.state.available_tools = disclosed

        if not StateValidator.validate_tools(self.state.available_tools):
            raise ApplicationError("Invalid tools configuration")

        # Resolve agent tools for workflow-level delegation
        await self._resolve_agent_tools()

    def _build_goal_from_request(self, request: AgentExecutionRequest) -> AgentGoal:
        """Build goal from execution request."""
        execution_limits = (request.effective_policy or {}).get("execution") or {}
        max_model_turns = execution_limits.get("max_model_turns")
        if not isinstance(max_model_turns, int) or max_model_turns <= 0:
            raise ValueError(
                "effective policy is missing required runtime limit execution.max_model_turns"
            )
        return AgentGoal(
            id=str(request.task_id),
            description=request.task_query,
            success_criteria=request.task_parameters.get("success_criteria", []),
            max_iterations=max_model_turns,
            requires_human_approval=request.requires_human_approval,
            context=request.task_parameters,
        )
