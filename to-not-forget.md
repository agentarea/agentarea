
  MCP OAuth Connect (end-to-end)

  - Client-side MCP OAuth flow (RFC 9728/8414/7591/PKCE) for connecting to remote MCP servers
  - Sentry MCP connected and working with OAuth
  - Tool discovery from remote MCPs, stored in json_spec.available_tools
  - URL-type instances skip Temporal workflow, use "connected" status (teal badge)
  - Known provider fallback for GitHub (no DCR support)

  Agent Tool Execution

  - MCP tools injected into agent execution (discovery → injection → tool calls)
  - Per-tool enable/disable + "requires approval" toggles in agent settings
  - Human approval flow: HumanApprovalRequested → pause → signal → HumanApprovalReceived/Denied stored in DB
  - Tool discovery resolves by UUID (not just name)
  - MCPToolFactory reads tools from json_spec.available_tools
  - ToolSettingsYAML.allowed_tools accepts per-tool objects with requires_user_confirmation

  Cost Tracking

  - Cost extraction via litellm.completion_cost() after streaming
  - Cost stored in task result and shown in tasks table ($X.XXXX)
  - Total sum row at bottom of tasks table
  - Tasks page now uses global /v1/tasks/ endpoint (includes total_cost)

  UI Improvements

  - Event dedup: ToolCallStarted/Completed and approval events merged in history
  - Approval UI: shows Approved/Denied after resolution, collapses, green checkmark
  - Tool icon: wrench instead of spinning gear, iconUrl prop for future tool-specific icons
  - Task description truncated in table
  - AgentArea proxy URL on MCP instance detail page
  - Agent active task count in agents table
  - Payment received/spent placeholders in BudgetInfo
  - Builtin tools route fix (/tools before /{agent_id})
  - Removed WorkflowStarted from visible events

  Bug Fixes

  - event_orm.event_metadata not .metadata (SQLAlchemy collision)
  - MCPAuthService.get() → get_by_id()
  - MCPToolRequest.tools not .tools_config
  - workflow.uuid4() for Temporal determinism
  - Temporal signal args=[] format
  - BaseSecretManagerDep removed from public OAuth callback
  - sse_client timeout as int not timedelta
  - SQLAlchemy session close race condition
  - a2ui_enabled column added to DB
  - Tool hash (SHA256) + change detection on re-discovery

  ---
  Needs to be addressed later

  Critical

  - UI Approve button on /tasks/[id] — wired up but needs hard refresh to work; SSE should push approval state updates live
  - Cost for non-streaming path — self.model_id reference still broken in ainvoke (non-streaming); only streaming path fixed

  Important

  - Event pipeline performance — 4 transformation layers, re-processes on every render (FIXME'd)
  - Tool-specific icons — iconUrl prop added to MessageWrapper but no lookup from server_instance_id → icon yet
  - ToolSettingsYAML.allowed_tools: list[Any] — should be a proper typed model (FIXME'd)
  - Duplicate HumanApprovalReceived events — emitted twice per approval, minor
  - Money storage format — costs stored as float, should be Decimal for precision
  - ToolCallCompleted after approval — should reference escalation_id to merge into single timeline entry (FIXME'd)

  Nice to have

  - Proxy URL for individual instances (infrastructure exists for bundles, not individual URL-type)
  - MCP server spec icons in catalog
  - WorkflowStarted replaced with task description as first message
  - Payment integration (agent paid/received) — placeholders in place