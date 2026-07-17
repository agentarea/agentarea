export type RequirementPriority = "must" | "should";
export type RequirementStatus = "implemented" | "todo";

export type FunctionalRequirement = {
  id: string;
  priority: RequirementPriority;
  title: string;
  description: string;
  acceptance: string[];
  status: RequirementStatus;
};

export const functionalRequirements: FunctionalRequirement[] = [
  {
    id: "FR-01",
    priority: "must",
    title: "Authentication and protected app shell",
    description:
      "Users authenticate through real Kratos and protected application routes render only with a live session.",
    acceptance: [
      "Unauthenticated users are redirected to login from protected routes.",
      "A real Kratos browser session opens the main shell.",
      "The API accepts a tokenized Kratos JWT for protected endpoints.",
    ],
    status: "implemented",
  },
  {
    id: "FR-02",
    priority: "must",
    title: "Workspace membership and invitations",
    description:
      "Workspace owners invite users, invitees accept, and membership is reflected in protected workspace APIs.",
    acceptance: [
      "Owner creates a workspace invitation for another Kratos identity.",
      "Invitee accepts the token through the backend.",
      "Invitee can list members of the invited workspace after accepting.",
    ],
    status: "implemented",
  },
  {
    id: "FR-03",
    priority: "must",
    title: "Agent lifecycle",
    description:
      "Users can create, inspect, edit, and delete agents with selected model/tool configuration.",
    acceptance: [
      "Create agent validates required fields and persists submitted configuration.",
      "Agent detail page shows the created agent and selected model/tools.",
      "Edit and delete actions update the listing and detail routes.",
    ],
    status: "implemented",
  },
  {
    id: "FR-04",
    priority: "must",
    title: "Provider configs and model instances",
    description:
      "Admins configure LLM providers, discover/test models, and use configured model instances from agent flows.",
    acceptance: [
      "Provider config can be created with a masked secret.",
      "Model discovery/test exposes success and failure states.",
      "Created model instance is selectable in agent creation.",
    ],
    status: "implemented",
  },
  {
    id: "FR-05",
    priority: "must",
    title: "Task creation and execution",
    description:
      "Users can start an agent task and observe status changes through the real task pipeline.",
    acceptance: [
      "Task creation returns a task id for a real agent.",
      "Task detail shows running state and reaches terminal success or controlled failure.",
      "Task appears in global task lists after creation.",
    ],
    status: "implemented",
  },
  {
    id: "FR-06",
    priority: "must",
    title: "Chat and SSE task events",
    description:
      "Chat/task screens stream task events, LLM chunks, tool calls, and terminal events without losing ordering.",
    acceptance: [
      "Submitting a message creates a task.",
      "SSE stream appends chunks/events in order.",
      "Failure events clear loading state and remain visible.",
    ],
    status: "implemented",
  },
  {
    id: "FR-07",
    priority: "must",
    title: "MCP server and instance setup",
    description:
      "Users can add MCP servers/instances, verify configuration, and see deploy/health state.",
    acceptance: [
      "Docker/command/external MCP form validates required fields.",
      "Instance verification result is visible.",
      "Secrets are masked after submit.",
    ],
    status: "implemented",
  },
  {
    id: "FR-08",
    priority: "must",
    title: "OpenAPI tool connection setup",
    description:
      "Users can register OpenAPI specs, preview discovered tools, and attach them to agents.",
    acceptance: [
      "OpenAPI URL or JSON spec preview discovers operations.",
      "Invalid specs show a blocking validation error.",
      "Created connection appears in tool selection surfaces.",
    ],
    status: "implemented",
  },
  {
    id: "FR-09",
    priority: "must",
    title: "Trigger creation and webhook execution",
    description:
      "Users create cron/webhook triggers, manage lifecycle, and public webhook requests create task activity.",
    acceptance: [
      "Cron trigger creation validates schedule and target agent.",
      "Webhook trigger exposes a callable webhook URL.",
      "Enable, disable, delete, and webhook execution states are visible.",
    ],
    status: "implemented",
  },
  {
    id: "FR-10",
    priority: "must",
    title: "Email delivery and Mailpit capture",
    description:
      "Local real-stack emails are delivered through the dev SMTP catcher and can be asserted through Mailpit.",
    acceptance: [
      "Kratos registration or recovery emits an email.",
      "Mailpit receives the message for the generated recipient.",
      "Subject and snippet match the expected flow.",
    ],
    status: "implemented",
  },
  {
    id: "FR-11",
    priority: "should",
    title: "Network topology",
    description:
      "Users can inspect graph topology for agents, tools, triggers, tasks, and related resources.",
    acceptance: [
      "Topology route renders nodes/edges from real API data.",
      "Filters change visible graph content.",
      "Selecting a node opens details or navigates to the resource.",
    ],
    status: "todo",
  },
  {
    id: "FR-12",
    priority: "should",
    title: "Skills and catalog flows",
    description:
      "Users can browse skills/catalog entries, inspect details, install or associate skills with agents/projects.",
    acceptance: [
      "Catalog/listing route renders real entries or empty state.",
      "Skill detail exposes content/files.",
      "Install/associate action updates the relevant resource.",
    ],
    status: "todo",
  },
  {
    id: "FR-13",
    priority: "should",
    title: "Projects and files",
    description:
      "Users manage projects, associate resources, upload/download files, and see missing-file errors.",
    acceptance: [
      "Project CRUD works against the real API.",
      "Agent/skill/MCP associations are reflected on project detail.",
      "File upload/download and missing-file error states are visible.",
    ],
    status: "todo",
  },
  {
    id: "FR-14",
    priority: "should",
    title: "API keys and secrets",
    description:
      "Users create one-time API keys, revoke keys, and manage masked secrets without leaking values.",
    acceptance: [
      "Created API key is revealed once and hidden after refresh.",
      "Revocation removes or marks the key as revoked.",
      "Secret values are never present in DOM after submit.",
    ],
    status: "todo",
  },
  {
    id: "FR-15",
    priority: "should",
    title: "Policies, approvals, and governance audit",
    description:
      "Users configure policies, resolve approval requests, and audit logs reflect significant actions.",
    acceptance: [
      "Policy create/edit preview reflects effective rules.",
      "Approval approve/deny action resolves the request.",
      "Audit filters find relevant actions after they occur.",
    ],
    status: "todo",
  },
  {
    id: "FR-16",
    priority: "should",
    title: "Workspace import and export",
    description:
      "Users export workspace configuration, reject invalid imports, and import valid bundles.",
    acceptance: [
      "Export downloads a YAML/JSON artifact.",
      "Invalid import shows validation errors.",
      "Valid import refreshes listed workspace resources.",
    ],
    status: "todo",
  },
  {
    id: "FR-17",
    priority: "should",
    title: "Dashboard, inbox, budgets, and operational views",
    description:
      "Operational surfaces render real data, empty states, degraded states, and filters without breaking shell navigation.",
    acceptance: [
      "Dashboard and inbox render with real API responses.",
      "Budgets route exposes current balance/limits or empty state.",
      "Filters/loading/error states remain actionable.",
    ],
    status: "todo",
  },
  {
    id: "FR-18",
    priority: "must",
    title: "Long conversation context management",
    description:
      "Long-running conversations are compacted before exceeding the model context window while preserving task intent, recent turns, and tool call/result integrity.",
    acceptance: [
      "Context usage is estimated against the selected model context_window before LLM calls.",
      "When context crosses the compaction threshold, older middle messages are summarized instead of blindly truncated.",
      "System prompt, initial task, recent turns, and complete tool_use/tool_result pairs are preserved after compaction.",
      "A long task continues after compaction without provider context-window or orphaned-tool-result errors.",
    ],
    status: "todo",
  },
  {
    id: "FR-19",
    priority: "must",
    title: "Agent task delegation",
    description:
      "Coordinator agents can delegate work to specialist agents, track child task outcomes, and surface delegation progress/results to users.",
    acceptance: [
      "Agent tools expose delegate_to_* actions for configured specialist agents.",
      "A coordinator task starts child tasks for selected specialists.",
      "Delegation started/completed/failed events are visible in task event history.",
      "Parent task summary and artifacts reflect child task results without cross-workspace leakage.",
    ],
    status: "todo",
  },
];

export function requirementTitle(id: string, scenario: string) {
  const requirement = functionalRequirements.find((item) => item.id === id);
  if (!requirement) {
    throw new Error(`Unknown functional requirement: ${id}`);
  }
  return `[${id}] ${requirement.title}: ${scenario}`;
}
