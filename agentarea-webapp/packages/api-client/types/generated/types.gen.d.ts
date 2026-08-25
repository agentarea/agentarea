export type ClientOptions = {
    baseUrl: `${string}://${string}` | (string & {});
};
/**
 * A2UIActionPayload
 *
 * Validated A2UI action payload from the frontend.
 */
export type A2UiActionPayload = {
    /**
     * Context
     */
    context?: {
        [key: string]: unknown;
    };
    /**
     * Name
     */
    name: string;
    /**
     * Source Component Id
     */
    source_component_id?: string;
    /**
     * Surface Id
     */
    surface_id: string;
};
/**
 * APIKeyCreateRequest
 */
export type ApiKeyCreateRequest = {
    /**
     * Expires In Days
     *
     * Optional expiry in days (omit for non-expiring)
     */
    expires_in_days?: number | null;
    /**
     * Name
     *
     * Human-friendly label for this API key
     */
    name: string;
};
/**
 * APIKeyCreateResponse
 *
 * Extends APIKeyResponse with the raw token — shown ONCE at creation.
 */
export type ApiKeyCreateResponse = {
    /**
     * Access Count
     */
    access_count: number;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Expires At
     */
    expires_at: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Last Accessed At
     */
    last_accessed_at: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Token
     *
     * Raw token value — copy it now, it won't be shown again
     */
    token: string;
    /**
     * Token Prefix
     */
    token_prefix: string;
};
/**
 * APIKeyResponse
 */
export type ApiKeyResponse = {
    /**
     * Access Count
     */
    access_count: number;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Expires At
     */
    expires_at: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Last Accessed At
     */
    last_accessed_at: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Token Prefix
     */
    token_prefix: string;
};
/**
 * AcceptInvitationBody
 */
export type AcceptInvitationBody = {
    /**
     * Token
     */
    token: string;
};
/**
 * AcceptInvitationResponse
 */
export type AcceptInvitationResponse = {
    /**
     * Invitation Id
     */
    invitation_id: string;
    /**
     * User Id
     */
    user_id: string;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * AddSkillRequest
 */
export type AddSkillRequest = {
    /**
     * Skill Id
     */
    skill_id: string;
};
/**
 * AgentAuthentication
 */
export type AgentAuthentication = {
    /**
     * Credentials
     */
    credentials?: string | null;
    /**
     * Schemes
     */
    schemes: Array<string>;
};
/**
 * AgentCapabilities
 */
export type AgentCapabilities = {
    /**
     * Extendedagentcard
     */
    extendedAgentCard?: boolean;
    /**
     * Extensions
     */
    extensions?: Array<{
        [key: string]: unknown;
    }> | null;
    /**
     * Pushnotifications
     */
    pushNotifications?: boolean;
    /**
     * Streaming
     */
    streaming?: boolean;
};
/**
 * AgentCard
 */
export type AgentCard = {
    authentication?: AgentAuthentication | null;
    capabilities: AgentCapabilities;
    /**
     * Defaultinputmodes
     */
    defaultInputModes?: Array<string>;
    /**
     * Defaultoutputmodes
     */
    defaultOutputModes?: Array<string>;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Documentationurl
     */
    documentationUrl?: string | null;
    /**
     * Name
     */
    name: string;
    provider?: AgentProvider | null;
    /**
     * Security
     */
    security?: Array<{
        [key: string]: Array<string>;
    }> | null;
    /**
     * Securityschemes
     */
    securitySchemes?: {
        [key: string]: unknown;
    } | null;
    /**
     * Skills
     */
    skills: Array<AgentSkill>;
    /**
     * Supportedinterfaces
     */
    supportedInterfaces: Array<AgentInterface>;
    /**
     * Version
     */
    version?: string;
};
/**
 * AgentCreate
 *
 * Payload for creating an agent.
 *
 * ``model_id`` is the UUID of a model instance configured in the workspace —
 * the runtime has no other interpretation of it. Omit it (or pass ``null``) to
 * create an agent with no model bound yet; such an agent cannot be run until a
 * model is assigned.
 */
export type AgentCreate = {
    /**
     * A2Ui Enabled
     *
     * Expose this agent over the A2UI protocol.
     */
    a2ui_enabled?: boolean | null;
    /**
     * Agent Type
     *
     * DEPRECATED — stored and echoed back, but the runtime never reads it, so every agent behaves as 'stateless' regardless of this value. Conversation history does not currently survive across runs. Do not branch on this field.
     *
     * @deprecated
     */
    agent_type?: 'stateless' | 'stateful';
    /**
     * Description
     *
     * Short summary of what the agent does.
     */
    description?: string;
    /**
     * Event subscriptions that auto-trigger this agent.
     */
    events_config?: EventsConfig | null;
    /**
     * Instruction
     *
     * System prompt / behavioural instructions for the agent.
     */
    instruction?: string;
    /**
     * Model Id
     *
     * UUID of a model instance in this workspace (see GET /v1/model-instances). Null means no model is bound yet and the agent cannot be run.
     */
    model_id?: string | null;
    /**
     * Name
     *
     * Human-readable agent name (unique per workspace).
     */
    name: string;
    /**
     * Planning
     *
     * Enable explicit planning step before execution.
     */
    planning?: boolean | null;
    /**
     * Skill Ids
     *
     * UUIDs of skills to attach to the agent.
     */
    skill_ids?: Array<string> | null;
    /**
     * Tools
     *
     * Tools attached to the agent (code/mcp/agent/openapi).
     */
    tools?: Array<CodeToolConfig | McpToolConfigInput | AgentToolConfig | OpenApiToolConfig> | null;
};
/**
 * AgentInterface
 *
 * A2A v1.0.0 AgentInterface — a (url, protocolBinding, protocolVersion) tuple.
 */
export type AgentInterface = {
    /**
     * Protocolbinding
     */
    protocolBinding?: string;
    /**
     * Protocolversion
     */
    protocolVersion?: string;
    /**
     * Tenant
     */
    tenant?: string | null;
    /**
     * Url
     */
    url: string;
};
/**
 * AgentOverviewResponse
 */
export type AgentOverviewResponse = {
    /**
     * Cost Mtd Usd
     */
    cost_mtd_usd: number;
    /**
     * Cost Today Usd
     */
    cost_today_usd: number;
    /**
     * Daily Spend
     */
    daily_spend: Array<DailySpendPoint>;
    /**
     * Daily Tasks
     */
    daily_tasks: Array<DailyTaskCounts>;
    /**
     * Last Activity At
     */
    last_activity_at: string | null;
    /**
     * Tasks Done Today
     */
    tasks_done_today: number;
    /**
     * Tasks Failed Today
     */
    tasks_failed_today: number;
    /**
     * Upcoming
     */
    upcoming: Array<UpcomingItem>;
};
/**
 * AgentProvider
 */
export type AgentProvider = {
    /**
     * Organization
     */
    organization: string;
    /**
     * Url
     */
    url?: string | null;
};
/**
 * AgentResponse
 */
export type AgentResponse = {
    /**
     * A2Ui Enabled
     */
    a2ui_enabled?: boolean | null;
    /**
     * Agent Type
     */
    agent_type?: string;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Events Config
     */
    events_config?: {
        [key: string]: unknown;
    } | null;
    /**
     * Id
     */
    id: string;
    /**
     * Instruction
     */
    instruction?: string | null;
    /**
     * Is Catalog
     */
    is_catalog?: boolean;
    /**
     * Model Id
     */
    model_id?: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Planning
     */
    planning?: boolean | null;
    /**
     * Registry Item Id
     */
    registry_item_id?: string | null;
    /**
     * Skills
     */
    skills?: Array<{
        [key: string]: unknown;
    }> | null;
    /**
     * Slug
     */
    slug: string;
    /**
     * Status
     */
    status: string;
    /**
     * Tools
     */
    tools?: Array<CodeToolConfig | McpToolConfigOutput | AgentToolConfig | OpenApiToolConfig> | null;
    /**
     * Update Available
     */
    update_available?: boolean;
};
/**
 * AgentRow
 */
export type AgentRow = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Cost Mtd Usd
     */
    cost_mtd_usd: number;
    /**
     * Cost Today Usd
     */
    cost_today_usd: number;
    /**
     * Last Activity At
     */
    last_activity_at: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Recent Task Names
     */
    recent_task_names: Array<string>;
    /**
     * Tasks Done Today
     */
    tasks_done_today: number;
    /**
     * Tasks Failed Today
     */
    tasks_failed_today: number;
};
/**
 * AgentSkill
 */
export type AgentSkill = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Examples
     */
    examples?: Array<string> | null;
    /**
     * Id
     */
    id: string;
    /**
     * Inputmodes
     */
    inputModes?: Array<string> | null;
    /**
     * Name
     */
    name: string;
    /**
     * Outputmodes
     */
    outputModes?: Array<string> | null;
    /**
     * Securityrequirements
     */
    securityRequirements?: Array<{
        [key: string]: Array<string>;
    }> | null;
    /**
     * Tags
     */
    tags?: Array<string> | null;
};
/**
 * AgentToolConfig
 */
export type AgentToolConfig = {
    /**
     * Name
     */
    name: string;
    settings?: AgentToolSettings | null;
    /**
     * Type
     */
    type?: 'agent';
};
/**
 * AgentToolSettings
 *
 * Settings for an agent-to-agent (delegation) tool.
 *
 * ``a2a_url`` selects the *remote* transport binding; absent → same-platform
 * direct delegation. Lives here only — A2A is a per-edge binding, not a
 * property every tool type carries.
 */
export type AgentToolSettings = {
    /**
     * A2A Url
     */
    a2a_url?: string | null;
    /**
     * Description Override
     */
    description_override?: string | null;
    /**
     * Requires User Confirmation
     */
    requires_user_confirmation?: boolean | null;
};
/**
 * AgentUpdate
 *
 * Patch payload for an agent. All fields optional — unset = unchanged.
 */
export type AgentUpdate = {
    /**
     * A2Ui Enabled
     */
    a2ui_enabled?: boolean | null;
    /**
     * Agent Type
     */
    agent_type?: 'stateless' | 'stateful' | null;
    /**
     * Capabilities
     */
    capabilities?: Array<string> | null;
    /**
     * Description
     */
    description?: string | null;
    events_config?: EventsConfig | null;
    /**
     * Instruction
     */
    instruction?: string | null;
    /**
     * Model Id
     */
    model_id?: string | null;
    /**
     * Name
     */
    name?: string | null;
    /**
     * Planning
     */
    planning?: boolean | null;
    /**
     * Skill Ids
     */
    skill_ids?: Array<string> | null;
    /**
     * Tools
     */
    tools?: Array<CodeToolConfig | McpToolConfigInput | AgentToolConfig | OpenApiToolConfig> | null;
};
/**
 * AnalyzeRequest
 *
 * Analyze a bundle into an import preview.
 *
 * Provide exactly one of ``source`` (pasted text) or ``source_url`` (a URL the
 * server fetches behind the SSRF guard). ``source_url`` is what a landing-page
 * deep-link (`/bundles/import?src=<url>`) uses for one-click installs.
 */
export type AnalyzeRequest = {
    /**
     * Source
     *
     * Raw bundle source text (YAML or JSON).
     */
    source?: string | null;
    /**
     * Source Url
     *
     * URL to fetch raw bundle source from (YAML or JSON).
     */
    source_url?: string | null;
};
/**
 * ApprovalPolicy
 *
 * Human approval and escalation requirements.
 */
export type ApprovalPolicy = {
    /**
     * Approvers
     */
    approvers?: Array<string>;
    /**
     * Approvers By Tool
     */
    approvers_by_tool?: {
        [key: string]: Array<string>;
    };
    /**
     * Escalation Rules
     */
    escalation_rules?: Array<string>;
    /**
     * Requires Human Approval
     */
    requires_human_approval?: boolean | null;
};
/**
 * ArtifactEventResponse
 */
export type ArtifactEventResponse = {
    /**
     * Action
     */
    action: string;
    /**
     * Actor Type
     */
    actor_type: string;
    /**
     * Agent Id
     */
    agent_id?: string | null;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Created By
     */
    created_by: string;
    /**
     * Task Id
     */
    task_id?: string | null;
};
/**
 * ArtifactHistoryResponse
 */
export type ArtifactHistoryResponse = {
    /**
     * Events
     */
    events: Array<ArtifactEventResponse>;
    /**
     * Path
     */
    path: string;
};
/**
 * AssociationBody
 */
export type AssociationBody = {
    /**
     * Id
     */
    id: string;
};
/**
 * AuditEventResponse
 *
 * Audit event response schema.
 */
export type AuditEventResponse = {
    /**
     * Action
     */
    action: string;
    /**
     * Actor Id
     */
    actor_id: string;
    /**
     * Actor Type
     */
    actor_type: string;
    /**
     * Changes
     */
    changes: Array<{
        [key: string]: unknown;
    }> | null;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Event Metadata
     */
    event_metadata: {
        [key: string]: unknown;
    };
    /**
     * Id
     */
    id: string;
    /**
     * Request Id
     */
    request_id: string | null;
    /**
     * Resource Id
     */
    resource_id: string | null;
    /**
     * Resource Type
     */
    resource_type: string;
    /**
     * Source Ip
     */
    source_ip: string | null;
    /**
     * User Agent
     */
    user_agent: string | null;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * AuditLogListResponse
 *
 * Paginated audit log response.
 */
export type AuditLogListResponse = {
    /**
     * Events
     */
    events: Array<AuditEventResponse>;
    /**
     * Next Cursor
     */
    next_cursor: string | null;
};
/**
 * Blockers
 */
export type Blockers = {
    /**
     * Failed 24H
     */
    failed_24h: Array<FailedTaskBlocker>;
    /**
     * Hitl
     */
    hitl: Array<HitlBlocker>;
    /**
     * Wallet Exhausted
     */
    wallet_exhausted: Array<WalletExhaustedBlocker>;
};
/**
 * Body_import_workspace_config_file_v1_workspace_import_file_post
 */
export type BodyImportWorkspaceConfigFileV1WorkspaceImportFilePost = {
    /**
     * File
     *
     * YAML configuration file
     */
    file: Blob | File;
};
/**
 * Body_upload_file_v1_files_post
 */
export type BodyUploadFileV1FilesPost = {
    /**
     * File
     */
    file: Blob | File;
    /**
     * Purpose
     */
    purpose?: string;
};
/**
 * Body_upload_project_file_v1_projects__project_id__files_post
 */
export type BodyUploadProjectFileV1ProjectsProjectIdFilesPost = {
    /**
     * File
     */
    file: Blob | File;
};
/**
 * Body_upload_skill_v1_skills_upload_post
 */
export type BodyUploadSkillV1SkillsUploadPost = {
    /**
     * File
     *
     * ZIP file containing the skill package
     */
    file: Blob | File;
};
/**
 * BudgetPolicy
 *
 * Budget-related ceilings.
 */
export type BudgetPolicyInput = {
    /**
     * Monthly Spend Cap Usd
     */
    monthly_spend_cap_usd?: number | string | null;
    /**
     * Run Budget Usd
     */
    run_budget_usd?: number | string | null;
    /**
     * Service Budget Usd
     */
    service_budget_usd?: number | string | null;
};
/**
 * BudgetPolicy
 *
 * Budget-related ceilings.
 */
export type BudgetPolicyOutput = {
    /**
     * Monthly Spend Cap Usd
     */
    monthly_spend_cap_usd?: string | null;
    /**
     * Run Budget Usd
     */
    run_budget_usd?: string | null;
    /**
     * Service Budget Usd
     */
    service_budget_usd?: string | null;
};
/**
 * Bundle
 *
 * The canonical, fully-inlined package object.
 */
export type BundleInput = {
    /**
     * Agents
     */
    agents?: Array<BundleAgent>;
    /**
     * Automations
     */
    automations?: Array<BundleAutomation>;
    /**
     * Channels
     */
    channels?: Array<BundleChannel>;
    /**
     * Description
     */
    description?: string;
    /**
     * Display Name
     */
    display_name?: string | null;
    /**
     * Mcps
     */
    mcps?: Array<BundleMcp>;
    metadata?: BundleMetadata;
    /**
     * Name
     *
     * Stable package identifier (idempotency key).
     */
    name: string;
    /**
     * Policies
     */
    policies?: Array<BundlePolicy>;
    /**
     * Schema Version
     */
    schema_version?: string;
    /**
     * Setup
     */
    setup?: Array<SetupField>;
    /**
     * Skills
     */
    skills?: Array<BundleSkill>;
};
/**
 * Bundle
 *
 * The canonical, fully-inlined package object.
 */
export type BundleOutput = {
    /**
     * Agents
     */
    agents?: Array<BundleAgent>;
    /**
     * Automations
     */
    automations?: Array<BundleAutomation>;
    /**
     * Channels
     */
    channels?: Array<BundleChannel>;
    /**
     * Description
     */
    description?: string;
    /**
     * Display Name
     */
    display_name?: string | null;
    /**
     * Mcps
     */
    mcps?: Array<BundleMcp>;
    metadata?: BundleMetadata;
    /**
     * Name
     *
     * Stable package identifier (idempotency key).
     */
    name: string;
    /**
     * Policies
     */
    policies?: Array<BundlePolicy>;
    /**
     * Schema Version
     */
    schema_version?: string;
    /**
     * Setup
     */
    setup?: Array<SetupField>;
    /**
     * Skills
     */
    skills?: Array<BundleSkill>;
};
/**
 * BundleAgent
 *
 * An agent to create for the package.
 */
export type BundleAgent = {
    /**
     * Instruction
     */
    instruction?: string;
    /**
     * Key
     */
    key: string;
    /**
     * Mcps
     *
     * BundleMcp keys to attach as tools.
     */
    mcps?: Array<string>;
    /**
     * Model
     */
    model?: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Skills
     *
     * BundleSkill keys to attach.
     */
    skills?: Array<string>;
};
/**
 * BundleAutomation
 *
 * A scheduled run of one of the package's agents (maps to a CronTrigger).
 *
 * Automations are imported disabled by default; the user enables them after
 * verifying connections, mirroring the Zapier/Make "connect then activate"
 * flow.
 */
export type BundleAutomation = {
    /**
     * Agent
     *
     * BundleAgent key to invoke.
     */
    agent: string;
    /**
     * Cron
     *
     * 5- or 6-field cron expression.
     */
    cron: string;
    /**
     * Enabled
     */
    enabled?: boolean;
    /**
     * Key
     */
    key: string;
    /**
     * Prompt
     *
     * Task query passed to the agent on each run.
     */
    prompt: string;
    /**
     * Timezone
     */
    timezone?: string;
    /**
     * Type
     */
    type?: 'cron';
};
/**
 * BundleChannel
 *
 * A messaging channel that lets an agent receive and reply to messages.
 *
 * Installs as an inbound trigger (e.g. a Telegram webhook): a message to the
 * bot becomes a task for ``agent``, and the reply is delivered back on the same
 * channel. Credentials (a bot token) enter via ``bindings`` → ``${setup.x}``,
 * exactly like an MCP's secret bindings, so the token is never inlined.
 */
export type BundleChannel = {
    /**
     * Agent
     *
     * BundleAgent key that handles inbound messages.
     */
    agent: string;
    /**
     * Bindings
     *
     * Maps a credential the channel needs to a ${setup.x} reference, e.g. {'bot_token': '${setup.telegram_bot_token}'}.
     */
    bindings?: {
        [key: string]: string;
    };
    /**
     * Enabled
     */
    enabled?: boolean;
    /**
     * Key
     */
    key: string;
    /**
     * Name
     *
     * Display name for the created channel trigger.
     */
    name: string;
    /**
     * Prompt
     *
     * Task query template used for each inbound message.
     */
    prompt?: string;
    /**
     * Type
     *
     * Channel provider. Only Telegram in v0.1.0.
     */
    type?: 'telegram';
};
/**
 * BundleMcp
 *
 * An MCP server to provision for the package.
 */
export type BundleMcp = {
    /**
     * Bindings
     *
     * Maps an env var / header name the server needs to a ${setup.x} reference, e.g. {'GITHUB_TOKEN': '${setup.github_token}'}.
     */
    bindings?: {
        [key: string]: string;
    };
    /**
     * Json Spec
     *
     * Native MCP runtime spec. Must include 'type' (command|docker|url).
     */
    json_spec: {
        [key: string]: unknown;
    };
    /**
     * Key
     *
     * In-package reference key (agents point at this).
     */
    key: string;
    /**
     * Name
     *
     * Instance display name created in the workspace.
     */
    name: string;
};
/**
 * BundleMetadata
 *
 * Marketplace presentation metadata (parity with plugin/app listings).
 */
export type BundleMetadata = {
    /**
     * Capabilities
     *
     * e.g. ["interactive", "write"].
     */
    capabilities?: Array<string>;
    /**
     * Category
     */
    category?: string | null;
    /**
     * Developer
     *
     * Publisher name.
     */
    developer?: string | null;
    /**
     * Icon
     *
     * Icon URL or asset reference.
     */
    icon?: string | null;
    /**
     * Privacy Url
     */
    privacy_url?: string | null;
    /**
     * Terms Url
     */
    terms_url?: string | null;
    /**
     * Website
     */
    website?: string | null;
};
/**
 * BundlePolicy
 *
 * A governance rule the package installs (maps to a PolicyRule).
 *
 * Portable like everything else: ``subject`` is the literal "workspace" or a
 * BundleAgent ``key`` (never a DB id); the installer resolves it to a real
 * subject id. ``target``/``effect``/``params`` mirror the unified governance
 * rule model, so this is "our policy format" — not a new one.
 */
export type BundlePolicy = {
    /**
     * Condition
     *
     * Optional CEL condition.
     */
    condition?: string | null;
    /**
     * Effect
     */
    effect: 'allow' | 'deny' | 'cap' | 'approval' | 'safety';
    /**
     * Enabled
     */
    enabled?: boolean;
    /**
     * Key
     */
    key: string;
    /**
     * Message
     *
     * Human-readable reason.
     */
    message?: string | null;
    /**
     * Params
     *
     * Effect-specific params, e.g. {amount_usd, period} for cap.
     */
    params?: {
        [key: string]: unknown;
    };
    /**
     * Priority
     */
    priority?: number;
    /**
     * Subject
     *
     * "workspace" or a BundleAgent key the rule binds to.
     */
    subject?: string;
    /**
     * Target
     *
     * Selector, e.g. "tool:send_email", "spend", "content", "*".
     */
    target: string;
};
/**
 * BundleSkill
 *
 * A skill to create for the package.
 */
export type BundleSkill = {
    /**
     * Content
     *
     * SKILL.md markdown for source_type=content.
     */
    content?: string | null;
    /**
     * Key
     */
    key: string;
    /**
     * Name
     */
    name: string;
    /**
     * Source Type
     */
    source_type?: 'content' | 'github';
    /**
     * Source Url
     *
     * Repo URL for source_type=github.
     */
    source_url?: string | null;
};
/**
 * CheckRequest
 */
export type CheckRequest = {
    /**
     * Namespace
     */
    namespace: string;
    /**
     * Object
     */
    object: string;
    /**
     * Relation
     */
    relation: string;
    /**
     * Subject Id
     */
    subject_id: string;
};
/**
 * CheckResponse
 */
export type CheckResponse = {
    /**
     * Allowed
     */
    allowed: boolean;
};
/**
 * ClientCreate
 *
 * Payload for registering a client (agent-proxy).
 */
export type ClientCreate = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Kind
     */
    kind?: string;
    /**
     * Name
     */
    name: string;
    /**
     * Source Project Id
     */
    source_project_id?: string | null;
};
/**
 * ClientRef
 */
export type ClientRef = {
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
};
/**
 * ClientResponse
 */
export type ClientResponse = {
    /**
     * Created By
     */
    created_by: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Kind
     */
    kind: string;
    /**
     * Mcp Endpoint Url
     */
    mcp_endpoint_url?: string | null;
    /**
     * Mcp Instances
     */
    mcp_instances?: Array<ClientRef>;
    /**
     * Name
     */
    name: string;
    /**
     * Skills
     */
    skills?: Array<ClientRef>;
    /**
     * Source Project Id
     */
    source_project_id: string | null;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * ClientUpdate
 *
 * Patch payload for a client. Unset fields remain unchanged.
 */
export type ClientUpdate = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Kind
     */
    kind?: string | null;
    /**
     * Name
     */
    name?: string | null;
    /**
     * Source Project Id
     */
    source_project_id?: string | null;
};
/**
 * CodeToolConfig
 */
export type CodeToolConfig = {
    /**
     * Name
     */
    name: string;
    settings?: CodeToolSettings | null;
    /**
     * Type
     */
    type?: 'code';
};
/**
 * CodeToolSettings
 *
 * Settings for a built-in code toolset.
 */
export type CodeToolSettings = {
    /**
     * Disabled Methods
     */
    disabled_methods?: Array<string> | null;
    /**
     * Requires User Confirmation
     */
    requires_user_confirmation?: boolean | null;
};
/**
 * CollectionCreateRequest
 */
export type CollectionCreateRequest = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Name
     */
    name: string;
};
/**
 * CollectionDetailResponse
 */
export type CollectionDetailResponse = {
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
    /**
     * Skills
     */
    skills: Array<SkillRef>;
};
/**
 * CollectionSummaryResponse
 */
export type CollectionSummaryResponse = {
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
    /**
     * Skill Count
     */
    skill_count: number;
};
/**
 * CollectionUpdateRequest
 */
export type CollectionUpdateRequest = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Name
     */
    name?: string | null;
};
/**
 * ContentSafetyPolicy
 *
 * Content-safety governance controls.
 */
export type ContentSafetyPolicy = {
    /**
     * Output Sanitizer Enabled
     */
    output_sanitizer_enabled?: boolean | null;
    /**
     * Prompt Injection Detection Enabled
     */
    prompt_injection_detection_enabled?: boolean | null;
};
/**
 * ContinueTaskPayload
 */
export type ContinueTaskPayload = {
    /**
     * Additional Budget Usd
     */
    additional_budget_usd?: number | string | null;
    /**
     * Additional Iterations
     */
    additional_iterations?: number;
};
/**
 * CreateInvitationBody
 */
export type CreateInvitationBody = {
    /**
     * Email
     */
    email?: string | null;
    /**
     * Expires In Days
     */
    expires_in_days?: number | null;
};
/**
 * CreateWalletRequest
 */
export type CreateWalletRequest = {
    credentials?: WalletCredentialsSchema | null;
    mpp_config?: MppConfigSchema | null;
    /**
     * Service Budget Period
     */
    service_budget_period?: string;
    /**
     * Service Budget Usd
     */
    service_budget_usd?: number;
    /**
     * Wallet Type
     */
    wallet_type: string;
    x402_config?: X402ConfigSchema | null;
};
/**
 * CreateWorkspaceBody
 */
export type CreateWorkspaceBody = {
    /**
     * Name
     */
    name: string;
};
/**
 * DailySpendPoint
 */
export type DailySpendPoint = {
    /**
     * Date
     */
    date: string;
    /**
     * Usd
     */
    usd: number;
};
/**
 * DailyTaskCounts
 */
export type DailyTaskCounts = {
    /**
     * Completed
     */
    completed: number;
    /**
     * Date
     */
    date: string;
    /**
     * Failed
     */
    failed: number;
    /**
     * Input Required
     */
    input_required: number;
};
/**
 * DashboardResponse
 */
export type DashboardResponse = {
    /**
     * Agents
     */
    agents: Array<AgentRow>;
    blockers: Blockers;
    /**
     * Daily Spend
     */
    daily_spend: Array<DailySpendPoint>;
    /**
     * Daily Tasks
     */
    daily_tasks: Array<DailyTaskCounts>;
    spend: SpendCard;
};
/**
 * DiscoverPreviewModelResponse
 */
export type DiscoverPreviewModelResponse = {
    /**
     * Context Window
     */
    context_window: number;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Display Name
     */
    display_name: string;
    /**
     * Id
     */
    id: string;
    /**
     * Input Cost Per Token
     */
    input_cost_per_token?: number | null;
    /**
     * Is New
     */
    is_new?: boolean;
    /**
     * Max Output Tokens
     */
    max_output_tokens?: number | null;
    /**
     * Model Name
     */
    model_name: string;
    /**
     * Output Cost Per Token
     */
    output_cost_per_token?: number | null;
    /**
     * Supports Function Calling
     */
    supports_function_calling?: boolean;
    /**
     * Supports Reasoning
     */
    supports_reasoning?: boolean;
    /**
     * Supports Vision
     */
    supports_vision?: boolean;
};
/**
 * DiscoverPreviewRequest
 */
export type DiscoverPreviewRequest = {
    /**
     * Api Key
     */
    api_key?: string | null;
    /**
     * Endpoint Url
     */
    endpoint_url?: string | null;
    /**
     * Provider Key
     */
    provider_key: string;
};
/**
 * DiscoverPreviewResponse
 */
export type DiscoverPreviewResponse = {
    /**
     * Discovered
     */
    discovered: number;
    /**
     * Models
     */
    models: Array<DiscoverPreviewModelResponse>;
    /**
     * New Models
     */
    new_models: number;
};
/**
 * DiscoveredModelResponse
 */
export type DiscoveredModelResponse = {
    /**
     * Context Window
     */
    context_window: number;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Display Name
     */
    display_name: string;
    /**
     * Input Cost Per Token
     */
    input_cost_per_token?: number | null;
    /**
     * Is New
     */
    is_new?: boolean;
    /**
     * Max Output Tokens
     */
    max_output_tokens?: number | null;
    /**
     * Model Name
     */
    model_name: string;
    /**
     * Output Cost Per Token
     */
    output_cost_per_token?: number | null;
    /**
     * Supports Function Calling
     */
    supports_function_calling?: boolean;
    /**
     * Supports Reasoning
     */
    supports_reasoning?: boolean;
    /**
     * Supports Vision
     */
    supports_vision?: boolean;
};
/**
 * DiscoveryResponse
 */
export type DiscoveryResponse = {
    /**
     * Discovered
     */
    discovered: number;
    /**
     * Models
     */
    models: Array<DiscoveredModelResponse>;
    /**
     * New Models
     */
    new_models: number;
};
/**
 * EffectivePolicy
 *
 * Resolved immutable policy snapshot.
 */
export type EffectivePolicy = {
    approval?: ApprovalPolicy | null;
    budget?: BudgetPolicyOutput | null;
    content_safety?: ContentSafetyPolicy | null;
    execution?: ExecutionLimitsPolicy | null;
    /**
     * Resolver Version
     */
    resolver_version?: string;
    /**
     * Source Policy Ids
     */
    source_policy_ids?: Array<string>;
    tokens?: TokenPolicy | null;
    tools?: ToolsPolicy | null;
};
/**
 * EffectivePolicyPreviewRequest
 *
 * Body for dry-run effective-policy resolution.
 */
export type EffectivePolicyPreviewRequest = {
    /**
     * Agent Id
     */
    agent_id?: string | null;
    task_policy?: PolicyDocument | null;
};
/**
 * EffectivePolicyResponse
 */
export type EffectivePolicyResponse = {
    effective_policy: EffectivePolicy;
};
/**
 * EntityKind
 */
export type EntityKind = 'mcp' | 'skill' | 'agent' | 'channel' | 'automation' | 'policy';
/**
 * EntityStatus
 */
export type EntityStatus = 'will_create' | 'already_exists' | 'unsupported';
/**
 * EscalationResolution
 */
export type EscalationResolution = {
    /**
     * Approved
     */
    approved: boolean;
    /**
     * Comment
     */
    comment?: string;
    /**
     * Escalation Id
     */
    escalation_id: string;
};
/**
 * EventConfig
 *
 * One event subscription for an agent.
 */
export type EventConfig = {
    /**
     * Config
     *
     * Event-specific configuration.
     */
    config?: {
        [key: string]: unknown;
    } | null;
    /**
     * Enabled
     *
     * Whether this subscription is active.
     */
    enabled?: boolean;
    /**
     * Event Type
     *
     * Event type the agent listens to.
     */
    event_type: string;
};
/**
 * EventsConfig
 *
 * Per-agent event subscriptions.
 */
export type EventsConfig = {
    /**
     * Events
     */
    events?: Array<EventConfig> | null;
};
/**
 * ExecutionCorrelationResponse
 *
 * Response model for execution correlation data.
 */
export type ExecutionCorrelationResponse = {
    /**
     * Executions
     */
    executions: Array<{
        [key: string]: unknown;
    }>;
    /**
     * Has Next
     */
    has_next: boolean;
    /**
     * Page
     */
    page: number;
    /**
     * Page Size
     */
    page_size: number;
    /**
     * Total
     */
    total: number;
};
/**
 * ExecutionHistoryResponse
 *
 * Response model for paginated execution history.
 */
export type ExecutionHistoryResponse = {
    /**
     * Executions
     */
    executions: Array<TriggerExecutionResponse>;
    /**
     * Has Next
     */
    has_next: boolean;
    /**
     * Page
     */
    page: number;
    /**
     * Page Size
     */
    page_size: number;
    /**
     * Total
     */
    total: number;
};
/**
 * ExecutionLimitsPolicy
 *
 * Ceilings for the agent loop and tool execution.
 */
export type ExecutionLimitsPolicy = {
    /**
     * Max Model Turns
     */
    max_model_turns?: number | null;
    /**
     * Max Tool Calls Per Turn
     */
    max_tool_calls_per_turn?: number | null;
    /**
     * Max Tool Calls Total
     */
    max_tool_calls_total?: number | null;
};
/**
 * ExecutionMetricsResponse
 *
 * Response model for execution metrics.
 */
export type ExecutionMetricsResponse = {
    /**
     * Avg Execution Time Ms
     */
    avg_execution_time_ms: number;
    /**
     * Failed Executions
     */
    failed_executions: number;
    /**
     * Failure Rate
     */
    failure_rate: number;
    /**
     * Max Execution Time Ms
     */
    max_execution_time_ms: number;
    /**
     * Min Execution Time Ms
     */
    min_execution_time_ms: number;
    /**
     * Period Hours
     */
    period_hours: number;
    /**
     * Success Rate
     */
    success_rate: number;
    /**
     * Successful Executions
     */
    successful_executions: number;
    /**
     * Timeout Executions
     */
    timeout_executions: number;
    /**
     * Total Executions
     */
    total_executions: number;
    /**
     * Trigger Id
     */
    trigger_id: string;
};
/**
 * ExecutionTimelineResponse
 *
 * Response model for execution timeline.
 */
export type ExecutionTimelineResponse = {
    /**
     * Period Hours
     */
    period_hours: number;
    /**
     * Timeline
     */
    timeline: Array<{
        [key: string]: unknown;
    }>;
    /**
     * Trigger Id
     */
    trigger_id: string;
};
/**
 * FailedTaskBlocker
 */
export type FailedTaskBlocker = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Agent Name
     */
    agent_name: string;
    /**
     * Error
     */
    error: string | null;
    /**
     * Occurred At
     */
    occurred_at: string;
    /**
     * Task Id
     */
    task_id: string;
};
/**
 * FundWalletRequest
 */
export type FundWalletRequest = {
    /**
     * Service Budget Usd
     */
    service_budget_usd: number;
};
/**
 * GovernanceOverlay
 */
export type GovernanceOverlay = {
    /**
     * Category
     */
    category: string;
    /**
     * Interceptor Name
     */
    interceptor_name: string;
    /**
     * Phases
     */
    phases: Array<string>;
};
/**
 * GraphNode
 */
export type GraphNode = {
    /**
     * Color
     */
    color: string;
    /**
     * Count
     */
    count?: number | null;
    /**
     * Id
     */
    id: string;
    /**
     * Kind
     */
    kind: 'agent' | 'collection' | 'mcp';
    /**
     * Name
     */
    name: string;
    /**
     * Subtitle
     */
    subtitle: string;
};
/**
 * GraphResponse
 */
export type GraphResponse = {
    /**
     * Edges
     */
    edges: Array<{
        [key: string]: unknown;
    }>;
    /**
     * Enabled
     */
    enabled: boolean;
    /**
     * Nodes
     */
    nodes: Array<GraphNode>;
    stats: GraphStats;
};
/**
 * GraphStats
 */
export type GraphStats = {
    /**
     * Direct Exception Count
     */
    direct_exception_count: number;
    /**
     * Governed Skill Count
     */
    governed_skill_count: number;
    /**
     * Rule Count
     */
    rule_count: number;
};
/**
 * HTTPValidationError
 */
export type HttpValidationError = {
    /**
     * Detail
     */
    detail?: Array<ValidationError>;
};
/**
 * HeaderInput
 *
 * One custom HTTP header attached to an OpenAPI connection.
 *
 * Non-safe header names (e.g. ``Authorization``) are stored encrypted in the
 * secret manager — pass the plaintext value here at create/update time.
 */
export type HeaderInput = {
    /**
     * Name
     *
     * HTTP header name. Allowed characters: letters, digits, '-', '_'.
     */
    name: string;
    /**
     * Value
     *
     * Header value. May not contain CR, LF, or NUL bytes.
     */
    value?: string;
};
/**
 * HeaderOutput
 *
 * Header metadata returned in API responses (secret values are masked).
 */
export type HeaderOutput = {
    /**
     * Name
     */
    name: string;
    /**
     * Secret
     */
    secret: boolean;
    /**
     * Value
     */
    value?: string | null;
};
/**
 * HitlBlocker
 */
export type HitlBlocker = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Agent Name
     */
    agent_name: string;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string;
    /**
     * Task Id
     */
    task_id: string;
};
/**
 * ImportPreview
 *
 * What the wizard renders before the user commits to installing.
 */
export type ImportPreview = {
    bundle: BundleOutput;
    /**
     * Entities
     */
    entities?: Array<PreviewEntity>;
    /**
     * Installable
     *
     * True when there are no blocking issues (setup may still be required).
     */
    installable: boolean;
    /**
     * Issues
     */
    issues?: Array<PreviewIssue>;
    /**
     * Setup
     */
    setup?: Array<SetupField>;
};
/**
 * ImportRequest
 *
 * Request body for importing workspace configuration.
 */
export type ImportRequest = {
    /**
     * Override Existing
     *
     * Override existing resources with same name
     */
    override_existing?: boolean;
    /**
     * Skip Missing Dependencies
     *
     * Skip resources with missing dependencies
     */
    skip_missing_dependencies?: boolean;
    /**
     * Yaml Content
     *
     * YAML configuration content
     */
    yaml_content: string;
};
/**
 * ImportResult
 *
 * Result of an import operation.
 */
export type ImportResult = {
    /**
     * Created Agents
     */
    created_agents?: number;
    /**
     * Created Mcp Instances
     */
    created_mcp_instances?: number;
    /**
     * Created Provider Configs
     */
    created_provider_configs?: number;
    /**
     * Created Skills
     */
    created_skills?: number;
    /**
     * Errors
     */
    errors?: Array<string>;
    /**
     * Success
     */
    success: boolean;
    /**
     * Warnings
     */
    warnings?: Array<string>;
};
/**
 * InboxResponse
 */
export type InboxResponse = {
    /**
     * Items
     */
    items: Array<TaskWithAgent>;
    /**
     * Page
     */
    page: number;
    /**
     * Page Size
     */
    page_size: number;
    /**
     * Total
     */
    total: number;
};
/**
 * InputSecretValue
 *
 * Secret value submitted through the protected input endpoint.
 */
export type InputSecretValue = {
    /**
     * Secret Name
     */
    secret_name?: string | null;
    /**
     * Value
     */
    value: string;
};
/**
 * InstallAction
 */
export type InstallAction = 'created' | 'reused' | 'skipped';
/**
 * InstallRequest
 *
 * Install a (previously analyzed, possibly edited) canonical bundle.
 */
export type InstallRequest = {
    bundle: BundleInput;
    /**
     * Setup Values
     *
     * Values for the bundle's setup fields, keyed by setup field key.
     */
    setup_values?: {
        [key: string]: unknown;
    };
};
/**
 * InstallResult
 */
export type InstallResult = {
    /**
     * Bundle Name
     */
    bundle_name: string;
    /**
     * Entities
     */
    entities?: Array<InstalledEntity>;
    /**
     * Installed Bundle Id
     */
    installed_bundle_id?: string | null;
};
/**
 * InstalledEntity
 */
export type InstalledEntity = {
    action: InstallAction;
    /**
     * Detail
     */
    detail?: string | null;
    /**
     * Id
     *
     * Created/reused entity id, when applicable.
     */
    id?: string | null;
    /**
     * Key
     */
    key: string;
    kind: EntityKind;
    /**
     * Name
     */
    name: string;
};
/**
 * InvitationCreatedResponse
 *
 * Same as InvitationResponse plus the plaintext token, returned ONCE.
 */
export type InvitationCreatedResponse = {
    /**
     * Accepted At
     */
    accepted_at: string | null;
    /**
     * Accepted By User Id
     */
    accepted_by_user_id: string | null;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Email
     */
    email: string | null;
    /**
     * Expires At
     */
    expires_at: string;
    /**
     * Id
     */
    id: string;
    /**
     * Invited By
     */
    invited_by: string;
    /**
     * Status
     */
    status: string;
    /**
     * Token
     */
    token: string;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * InvitationResponse
 */
export type InvitationResponse = {
    /**
     * Accepted At
     */
    accepted_at: string | null;
    /**
     * Accepted By User Id
     */
    accepted_by_user_id: string | null;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Email
     */
    email: string | null;
    /**
     * Expires At
     */
    expires_at: string;
    /**
     * Id
     */
    id: string;
    /**
     * Invited By
     */
    invited_by: string;
    /**
     * Status
     */
    status: string;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * IssueSeverity
 */
export type IssueSeverity = 'block' | 'warn';
/**
 * MCPAuthConfigCreateRequest
 */
export type McpAuthConfigCreateRequest = {
    /**
     * Auth Type
     *
     * One of: api_key, bearer, oauth2
     */
    auth_type: string;
    /**
     * Config
     *
     * Non-sensitive config (header_name, token_url, client_id, scopes, …)
     */
    config?: {
        [key: string]: unknown;
    };
    /**
     * Credentials
     *
     * Sensitive credentials encrypted at rest (header_value, token, client_secret, …)
     */
    credentials?: {
        [key: string]: unknown;
    };
    /**
     * Description
     */
    description?: string | null;
    /**
     * Name
     *
     * Human-readable name for this auth config
     */
    name: string;
};
/**
 * MCPAuthConfigResponse
 */
export type McpAuthConfigResponse = {
    /**
     * Auth Type
     */
    auth_type: string;
    /**
     * Config
     */
    config: {
        [key: string]: unknown;
    };
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
    /**
     * Updated At
     */
    updated_at: string;
};
/**
 * MCPAuthConfigUpdateRequest
 */
export type McpAuthConfigUpdateRequest = {
    /**
     * Config
     */
    config?: {
        [key: string]: unknown;
    } | null;
    /**
     * Credentials
     */
    credentials?: {
        [key: string]: unknown;
    } | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Name
     */
    name?: string | null;
};
/**
 * MCPContainersHealthResponse
 */
export type McpContainersHealthResponse = {
    /**
     * Healthy
     */
    healthy: number;
    /**
     * Instances
     */
    instances: Array<McpInstanceHealthResponse>;
    /**
     * Total
     */
    total: number;
};
/**
 * MCPInstanceConsumer
 *
 * An agent that has this MCP instance attached, and which of its tools it enabled.
 */
export type McpInstanceConsumer = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Agent Name
     */
    agent_name: string;
    /**
     * Agent Slug
     */
    agent_slug?: string | null;
    /**
     * Confirm Tools
     */
    confirm_tools?: Array<string>;
    /**
     * Enabled Tools
     */
    enabled_tools?: Array<string> | null;
};
/**
 * MCPInstanceHealthResponse
 *
 * One workload's health, as the calling workspace is entitled to see it.
 *
 * Deliberately just the verdict and its reason. The manager's own health body
 * is richer — container id, image, ports, the gateway path it serves the
 * workload on — and none of that is something a caller needs in order to learn
 * that a workload is up. It is dropped here rather than passed through, so the
 * endpoint cannot become a way to enumerate the data plane.
 */
export type McpInstanceHealthResponse = {
    /**
     * Healthy
     */
    healthy: boolean;
    /**
     * Instance Id
     */
    instance_id: string;
    /**
     * Name
     */
    name?: string | null;
    /**
     * Status
     */
    status: string;
};
/**
 * MCPServerConnectionCreateRequest
 */
export type McpServerConnectionCreateRequest = {
    instance: McpServerInstanceCreateWithoutSpec;
    server: McpServerCreate;
};
/**
 * MCPServerCreate
 *
 * Payload for creating an MCP server spec (catalog template).
 *
 * Either ``docker_image_url`` (for container-based servers) or
 * ``remote_url`` (for HTTP-based servers like GitHub Copilot) should be
 * supplied. ``env_schema`` describes the variables an instance built from
 * this spec needs to provide; secret entries (``isSecret: true``) are
 * routed through the secret manager rather than stored in plaintext.
 */
export type McpServerCreate = {
    /**
     * Cmd
     *
     * Custom command override for container CMD (e.g. switching between stdio and HTTP modes).
     */
    cmd?: Array<string> | null;
    /**
     * Description
     *
     * Short summary of what this MCP server provides.
     */
    description: string;
    /**
     * Docker Image Url
     *
     * Docker image URL for container-based MCP servers.
     */
    docker_image_url?: string | null;
    /**
     * Env Schema
     *
     * Environment-variable schema entries (KeyValueInput from the MCP registry). Each item has at least 'name' and 'description'; mark secrets with 'isSecret: true'.
     */
    env_schema?: Array<{
        [key: string]: unknown;
    }> | null;
    /**
     * Is Public
     *
     * If true, the spec is visible across workspaces.
     */
    is_public?: boolean;
    /**
     * Json Spec
     *
     * Raw ServerJSON spec as published by the MCP registry.
     */
    json_spec?: {
        [key: string]: unknown;
    } | null;
    /**
     * Name
     *
     * Human-readable MCP server name (unique per workspace).
     */
    name: string;
    /**
     * Registry Url
     *
     * Source registry URL the spec was imported from.
     */
    registry_url?: string | null;
    /**
     * Remote Url
     *
     * Remote endpoint URL for HTTP-based MCP servers.
     */
    remote_url?: string | null;
    /**
     * Tags
     *
     * Tags used for search and categorization.
     */
    tags?: Array<string>;
    /**
     * Version
     *
     * Semantic version of the MCP server spec.
     */
    version?: string;
};
/**
 * MCPServerInstanceCreate
 *
 * Payload for creating an MCP server instance.
 *
 * ``json_spec`` carries the connection configuration. Common shapes:
 *
 * - ``{"type": "url", "endpoint_url": "https://..."}``
 * - ``{"type": "docker", "environment": {...}, "env_vars": [...]}``
 * - ``{"type": "command", "command": [...], "environment": {...}}``
 * For URL-type instances the service synchronously verifies the endpoint;
 * docker/command kick off background verification.
 */
export type McpServerInstanceCreate = {
    /**
     * Auth Config Id
     *
     * ID of an MCP auth config (OAuth/credentials) to attach.
     */
    auth_config_id?: string | null;
    /**
     * Description
     *
     * Optional human-readable description of the instance.
     */
    description?: string | null;
    /**
     * Json Spec
     *
     * Connection configuration. Must include 'type' ('url' | 'docker' | 'command'); other keys depend on type.
     */
    json_spec: {
        [key: string]: unknown;
    };
    /**
     * Name
     *
     * Display name for this MCP server instance (unique per workspace).
     */
    name: string;
    /**
     * Server Spec Id
     *
     * ID of an existing MCP server spec to derive defaults from (env_schema, secret routing, etc.).
     */
    server_spec_id: string;
};
/**
 * MCPServerInstanceCreateWithoutSpec
 */
export type McpServerInstanceCreateWithoutSpec = {
    /**
     * Auth Config Id
     */
    auth_config_id?: string | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Json Spec
     */
    json_spec?: {
        [key: string]: unknown;
    };
    /**
     * Name
     */
    name: string;
};
/**
 * MCPServerInstanceResponse
 */
export type McpServerInstanceResponse = {
    /**
     * Auth Config Id
     */
    auth_config_id?: string | string | null;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Json Spec
     */
    json_spec: {
        [key: string]: unknown;
    };
    /**
     * Last Dispatch
     */
    last_dispatch?: {
        [key: string]: unknown;
    } | null;
    /**
     * Name
     */
    name: string;
    /**
     * Server Spec Id
     */
    server_spec_id: string;
    /**
     * Tools
     */
    tools?: Array<{
        [key: string]: unknown;
    }> | null;
    /**
     * Updated At
     */
    updated_at: string;
    /**
     * Verification
     */
    verification: {
        [key: string]: unknown;
    };
};
/**
 * MCPServerInstanceUpdate
 *
 * Patch payload for an MCP server instance. All fields optional — unset = unchanged.
 */
export type McpServerInstanceUpdate = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Json Spec
     */
    json_spec?: {
        [key: string]: unknown;
    } | null;
    /**
     * Name
     */
    name?: string | null;
};
/**
 * MCPServerResponse
 */
export type McpServerResponse = {
    /**
     * Cmd
     */
    cmd: Array<string> | null;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string;
    /**
     * Docker Image Url
     */
    docker_image_url?: string | null;
    /**
     * Env Schema
     */
    env_schema: Array<{
        [key: string]: unknown;
    }>;
    /**
     * Id
     */
    id: string;
    /**
     * Is Public
     */
    is_public: boolean;
    /**
     * Json Spec
     */
    json_spec?: {
        [key: string]: unknown;
    } | null;
    /**
     * Name
     */
    name: string;
    /**
     * Registry Url
     */
    registry_url?: string | null;
    /**
     * Remote Url
     */
    remote_url?: string | null;
    /**
     * Slug
     */
    slug: string;
    /**
     * Status
     */
    status: string;
    /**
     * Tags
     */
    tags: Array<string>;
    /**
     * Updated At
     */
    updated_at: string;
    /**
     * Version
     */
    version: string;
};
/**
 * MCPServerUpdate
 *
 * Patch payload for an MCP server spec. All fields optional — unset = unchanged.
 */
export type McpServerUpdate = {
    /**
     * Cmd
     */
    cmd?: Array<string> | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Docker Image Url
     */
    docker_image_url?: string | null;
    /**
     * Env Schema
     */
    env_schema?: Array<{
        [key: string]: unknown;
    }> | null;
    /**
     * Is Public
     */
    is_public?: boolean | null;
    /**
     * Json Spec
     */
    json_spec?: {
        [key: string]: unknown;
    } | null;
    /**
     * Name
     */
    name?: string | null;
    /**
     * Registry Url
     */
    registry_url?: string | null;
    /**
     * Remote Url
     */
    remote_url?: string | null;
    /**
     * Status
     *
     * Lifecycle status of the spec (e.g. 'active', 'deprecated').
     */
    status?: string | null;
    /**
     * Tags
     */
    tags?: Array<string> | null;
    /**
     * Version
     */
    version?: string | null;
};
/**
 * MPPConfigSchema
 */
export type MppConfigSchema = {
    /**
     * Chain Id
     */
    chain_id?: number | null;
    /**
     * Currency
     */
    currency?: string | null;
    /**
     * Decimals
     */
    decimals?: number;
    /**
     * Payment Method Types
     */
    payment_method_types?: Array<string>;
    /**
     * Recipient
     */
    recipient?: string | null;
    /**
     * Rpc Url
     */
    rpc_url?: string | null;
    /**
     * Session Budget Usd
     */
    session_budget_usd?: number;
    /**
     * Stripe Profile Id
     */
    stripe_profile_id?: string | null;
};
/**
 * McpInstanceAssociationBody
 */
export type McpInstanceAssociationBody = {
    /**
     * Id
     */
    id: string;
    /**
     * Namespace Prefix
     */
    namespace_prefix?: string | null;
};
/**
 * McpToolConfig
 */
export type McpToolConfigInput = {
    /**
     * Name
     */
    name: string;
    settings?: McpToolSettings | null;
    /**
     * Type
     */
    type?: 'mcp';
};
/**
 * McpToolConfig
 */
export type McpToolConfigOutput = {
    /**
     * Name
     */
    name: string;
    settings?: McpToolSettings | null;
    /**
     * Type
     */
    type?: 'mcp';
};
/**
 * McpToolPermission
 *
 * A single MCP tool the agent may call.
 *
 * Replaces the old ``list[Any]`` for ``allowed_tools`` (the former FIXME).
 * ``requires_user_confirmation`` is transport only: the API translates it into
 * an agent-scoped approval policy rule and does not persist it here, so it is
 * ``None`` at rest and reconstituted from rules on read.
 */
export type McpToolPermission = {
    /**
     * Requires User Confirmation
     */
    requires_user_confirmation?: boolean | null;
    /**
     * Tool Name
     */
    tool_name: string;
};
/**
 * McpToolSettings
 *
 * Settings for an MCP server tool (a subset of the server's tools).
 */
export type McpToolSettings = {
    /**
     * Allowed Tools
     */
    allowed_tools?: Array<McpToolPermission> | null;
    /**
     * Requires User Confirmation
     */
    requires_user_confirmation?: boolean | null;
};
/**
 * MemberResponse
 */
export type MemberResponse = {
    /**
     * Display Name
     */
    display_name?: string | null;
    /**
     * Email
     */
    email?: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Invitation Id
     */
    invitation_id: string | null;
    /**
     * Joined At
     */
    joined_at: string;
    /**
     * User Id
     */
    user_id: string;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * ModelInstanceBulkCreateRequest
 */
export type ModelInstanceBulkCreateRequest = {
    /**
     * Items
     */
    items: Array<ModelInstanceCreate>;
};
/**
 * ModelInstanceBulkCreateResponse
 */
export type ModelInstanceBulkCreateResponse = {
    /**
     * Failed
     */
    failed: Array<ModelInstanceBulkFailure>;
    /**
     * Failed Count
     */
    failed_count: number;
    /**
     * Succeeded
     */
    succeeded: Array<ModelInstanceResponse>;
    /**
     * Succeeded Count
     */
    succeeded_count: number;
};
/**
 * ModelInstanceBulkFailure
 */
export type ModelInstanceBulkFailure = {
    /**
     * Error
     */
    error: string;
    /**
     * Index
     */
    index: number;
    /**
     * Model Spec Id
     */
    model_spec_id: string;
};
/**
 * ModelInstanceCreate
 */
export type ModelInstanceCreate = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Is Public
     */
    is_public?: boolean;
    /**
     * Model Spec Id
     */
    model_spec_id: string;
    /**
     * Name
     */
    name: string;
    /**
     * Provider Config Id
     */
    provider_config_id: string;
};
/**
 * ModelInstanceResponse
 */
export type ModelInstanceResponse = {
    /**
     * Config Name
     */
    config_name?: string | null;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Is Public
     */
    is_public: boolean;
    /**
     * Model Display Name
     */
    model_display_name?: string | null;
    /**
     * Model Name
     */
    model_name?: string | null;
    /**
     * Model Spec Id
     */
    model_spec_id: string;
    /**
     * Name
     */
    name: string;
    /**
     * Provider Config Id
     */
    provider_config_id: string;
    /**
     * Provider Icon Url
     */
    provider_icon_url?: string | null;
    /**
     * Provider Key
     */
    provider_key?: string | null;
    /**
     * Provider Name
     */
    provider_name?: string | null;
    /**
     * Updated At
     */
    updated_at: string;
};
/**
 * ModelInstanceTestRequest
 */
export type ModelInstanceTestRequest = {
    /**
     * Model Spec Id
     */
    model_spec_id: string;
    /**
     * Provider Config Id
     */
    provider_config_id: string;
    /**
     * Test Message
     */
    test_message?: string | null;
};
/**
 * ModelInstanceTestResponse
 */
export type ModelInstanceTestResponse = {
    /**
     * Cost
     */
    cost?: number | null;
    /**
     * Error Type
     */
    error_type?: string | null;
    /**
     * Message
     */
    message: string;
    /**
     * Model Name
     */
    model_name?: string | null;
    /**
     * Provider Type
     */
    provider_type?: string | null;
    /**
     * Response Content
     */
    response_content?: string | null;
    /**
     * Success
     */
    success: boolean;
    /**
     * Tokens Used
     */
    tokens_used?: number | null;
};
/**
 * ModelSpecCreate
 */
export type ModelSpecCreate = {
    /**
     * Context Window
     */
    context_window: number;
    /**
     * Default Context Strategy
     */
    default_context_strategy?: string | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Display Name
     */
    display_name: string;
    /**
     * Input Cost Per Token
     */
    input_cost_per_token: number;
    /**
     * Is Active
     */
    is_active?: boolean;
    /**
     * Max Output Tokens
     */
    max_output_tokens?: number | null;
    /**
     * Model Name
     */
    model_name: string;
    /**
     * Output Cost Per Token
     */
    output_cost_per_token: number;
    /**
     * Provider Spec Id
     */
    provider_spec_id: string;
};
/**
 * ModelSpecUpdate
 */
export type ModelSpecUpdate = {
    /**
     * Context Window
     */
    context_window?: number | null;
    /**
     * Default Context Strategy
     */
    default_context_strategy?: string | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Display Name
     */
    display_name?: string | null;
    /**
     * Input Cost Per Token
     */
    input_cost_per_token?: number | null;
    /**
     * Is Active
     */
    is_active?: boolean | null;
    /**
     * Max Output Tokens
     */
    max_output_tokens?: number | null;
    /**
     * Output Cost Per Token
     */
    output_cost_per_token?: number | null;
};
/**
 * NetworkEdge
 */
export type NetworkEdge = {
    /**
     * Id
     */
    id: string;
    /**
     * Relation
     */
    relation: string;
    /**
     * Source
     */
    source: string;
    /**
     * Target
     */
    target: string;
};
/**
 * NetworkNode
 */
export type NetworkNode = {
    /**
     * Id
     */
    id: string;
    /**
     * Label
     */
    label: string;
    /**
     * Metadata
     */
    metadata?: {
        [key: string]: unknown;
    };
    /**
     * Status
     */
    status?: string | null;
    /**
     * Type
     */
    type: 'agent' | 'mcp_instance' | 'openapi_connection' | 'skill' | 'trigger';
};
/**
 * NetworkTopologyResponse
 */
export type NetworkTopologyResponse = {
    /**
     * Deployment Mode
     */
    deployment_mode?: string;
    /**
     * Edges
     */
    edges: Array<NetworkEdge>;
    /**
     * Governance
     */
    governance: Array<GovernanceOverlay>;
    /**
     * Nodes
     */
    nodes: Array<NetworkNode>;
};
/**
 * OAuthLinkCreateRequest
 */
export type OAuthLinkCreateRequest = {
    /**
     * Access Control
     *
     * Access control level: workspace | public
     */
    access_control?: string;
    /**
     * Expires In Days
     *
     * Optional link expiry in days
     */
    expires_in_days?: number | null;
    /**
     * Mcp Instance Id
     */
    mcp_instance_id: string;
    /**
     * Provider Config
     *
     * OAuth provider config: provider, auth_url, token_url, client_id, scopes, …
     */
    provider_config?: {
        [key: string]: unknown;
    };
};
/**
 * OAuthLinkResponse
 */
export type OAuthLinkResponse = {
    /**
     * Access Control
     */
    access_control: string;
    /**
     * Access Count
     */
    access_count: number;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Expires At
     */
    expires_at: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Last Accessed At
     */
    last_accessed_at: string | null;
    /**
     * Mcp Instance Id
     */
    mcp_instance_id: string;
    /**
     * Token
     */
    token: string;
};
/**
 * OpenAPIConnectionCreate
 *
 * Payload for creating an OpenAPI connection.
 *
 * The connection ties a base URL (where requests are sent) to an
 * OpenAPI 3.x specification (which is parsed eagerly into a tool list).
 * Provide either ``spec_url`` or ``spec_content`` — not both required.
 */
export type OpenApiConnectionCreate = {
    /**
     * Auth Config Id
     *
     * Optional MCPAuthConfig UUID for OAuth2 token rotation. When set, tokens are minted/refreshed on the connection's behalf.
     */
    auth_config_id?: string | null;
    /**
     * Base Url
     *
     * Base URL for API requests, e.g. 'https://api.example.com'.
     */
    base_url: string;
    /**
     * Custom Headers
     *
     * Custom HTTP headers attached to every request. Non-safe headers (e.g. Authorization) are stored encrypted in the secret manager.
     */
    custom_headers?: Array<HeaderInput> | null;
    /**
     * Description
     *
     * Optional human-readable summary of what this API exposes.
     */
    description?: string | null;
    /**
     * Name
     *
     * Display name for the connection (unique per workspace).
     */
    name: string;
    /**
     * Spec Content
     *
     * Inline OpenAPI 3.x spec as a JSON object. Use instead of ``spec_url`` when the spec host is unreachable from the API.
     */
    spec_content?: {
        [key: string]: unknown;
    } | null;
    /**
     * Spec Url
     *
     * URL to an OpenAPI 3.x JSON or YAML spec. The spec is fetched and parsed eagerly at create time so the connection is ready for use.
     */
    spec_url?: string | null;
};
/**
 * OpenAPIConnectionResponse
 */
export type OpenApiConnectionResponse = {
    /**
     * Auth Config Id
     */
    auth_config_id?: string | null;
    /**
     * Available Tools
     */
    available_tools?: Array<{
        [key: string]: unknown;
    }>;
    /**
     * Base Url
     */
    base_url: string;
    /**
     * Created At
     */
    created_at: unknown;
    /**
     * Custom Headers
     */
    custom_headers?: Array<HeaderOutput> | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
    /**
     * Spec Url
     */
    spec_url?: string | null;
    /**
     * Status
     */
    status: string;
    /**
     * Updated At
     */
    updated_at: unknown;
};
/**
 * OpenAPIConnectionUpdate
 *
 * Patch payload for an OpenAPI connection. All fields optional — unset = unchanged.
 */
export type OpenApiConnectionUpdate = {
    /**
     * Auth Config Id
     *
     * Optional MCPAuthConfig UUID for OAuth2 token rotation.
     */
    auth_config_id?: string | null;
    /**
     * Base Url
     */
    base_url?: string | null;
    /**
     * Custom Headers
     *
     * Replace the full custom-header set. Pass [] to clear all. Secret values are stored encrypted in the secret manager.
     */
    custom_headers?: Array<HeaderInput> | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Name
     */
    name?: string | null;
    /**
     * Spec Content
     */
    spec_content?: {
        [key: string]: unknown;
    } | null;
    /**
     * Spec Url
     */
    spec_url?: string | null;
};
/**
 * OpenApiToolConfig
 */
export type OpenApiToolConfig = {
    /**
     * Name
     */
    name: string;
    settings?: OpenApiToolSettings | null;
    /**
     * Type
     */
    type?: 'openapi';
};
/**
 * OpenApiToolSettings
 *
 * Settings for an OpenAPI connection tool.
 *
 * ``load_mode`` picks schema disclosure: "explicit" inlines every operation's
 * schema into each LLM call (legacy); "searchable" defers them behind a
 * ``load_tools`` meta-tool. Honored only for openapi tools — which is exactly
 * why it lives here and nowhere else.
 */
export type OpenApiToolSettings = {
    /**
     * Allowed Tools
     */
    allowed_tools?: Array<string> | null;
    /**
     * Load Mode
     */
    load_mode?: 'explicit' | 'searchable' | null;
    /**
     * Openapi Connection Id
     */
    openapi_connection_id?: string | null;
    /**
     * Requires User Confirmation
     */
    requires_user_confirmation?: boolean | null;
};
/**
 * PaginatedPaymentsResponse
 */
export type PaginatedPaymentsResponse = {
    /**
     * Items
     */
    items: Array<PaymentRecordResponse>;
    /**
     * Page
     */
    page: number;
    /**
     * Page Size
     */
    page_size: number;
    /**
     * Total
     */
    total: number;
};
/**
 * PaginatedResponse[MCPServerResponse]
 */
export type PaginatedResponseMcpServerResponse = {
    /**
     * Has Next
     */
    has_next: boolean;
    /**
     * Items
     */
    items: Array<McpServerResponse>;
    /**
     * Page
     */
    page: number;
    /**
     * Page Size
     */
    page_size: number;
    /**
     * Total
     */
    total: number;
};
/**
 * PaginatedResponse[SkillResponse]
 */
export type PaginatedResponseSkillResponse = {
    /**
     * Has Next
     */
    has_next: boolean;
    /**
     * Items
     */
    items: Array<SkillResponse>;
    /**
     * Page
     */
    page: number;
    /**
     * Page Size
     */
    page_size: number;
    /**
     * Total
     */
    total: number;
};
/**
 * PaymentRecordResponse
 */
export type PaymentRecordResponse = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Amount Usd
     */
    amount_usd: number;
    /**
     * Created At
     */
    created_at?: string | null;
    /**
     * Error Message
     */
    error_message?: string | null;
    /**
     * Execution Id
     */
    execution_id: string;
    /**
     * Id
     */
    id: string;
    /**
     * Protocol
     */
    protocol: string;
    /**
     * Protocol Metadata
     */
    protocol_metadata?: {
        [key: string]: unknown;
    } | null;
    /**
     * Recipient
     */
    recipient: string;
    /**
     * Status
     */
    status: string;
    /**
     * Tool Call Id
     */
    tool_call_id: string;
    /**
     * Tool Name
     */
    tool_name: string;
    /**
     * Tx Hash
     */
    tx_hash?: string | null;
};
/**
 * PolicyDocument
 *
 * Source policy document stored per scope.
 */
export type PolicyDocument = {
    approval?: ApprovalPolicy | null;
    budget?: BudgetPolicyInput | null;
    content_safety?: ContentSafetyPolicy | null;
    execution?: ExecutionLimitsPolicy | null;
    tokens?: TokenPolicy | null;
    tools?: ToolsPolicy | null;
};
/**
 * PolicyEffect
 *
 * What a rule does when it applies.
 */
export type PolicyEffect = 'allow' | 'deny' | 'cap' | 'approval' | 'safety' | 'egress';
/**
 * PolicyRuleCreateRequest
 *
 * Request body for creating a policy rule.
 */
export type PolicyRuleCreateRequest = {
    /**
     * Condition
     */
    condition?: string | null;
    effect: PolicyEffect;
    /**
     * Enabled
     */
    enabled?: boolean;
    /**
     * Params
     */
    params?: {
        [key: string]: unknown;
    };
    /**
     * Priority
     */
    priority?: number;
    /**
     * Subject Id
     */
    subject_id: string;
    subject_type: PolicySubjectType;
    /**
     * Target
     */
    target: string;
};
/**
 * PolicyRuleResponse
 *
 * Serialized policy rule returned to clients.
 */
export type PolicyRuleResponse = {
    /**
     * Condition
     */
    condition?: string | null;
    effect: PolicyEffect;
    /**
     * Enabled
     */
    enabled: boolean;
    /**
     * Id
     */
    id: string;
    /**
     * Params
     */
    params: {
        [key: string]: unknown;
    };
    /**
     * Priority
     */
    priority: number;
    /**
     * Subject Id
     */
    subject_id: string;
    subject_type: PolicySubjectType;
    /**
     * Target
     */
    target: string;
};
/**
 * PolicyRuleUpdateRequest
 *
 * Request body for partially updating a policy rule.
 */
export type PolicyRuleUpdateRequest = {
    /**
     * Condition
     */
    condition?: string | null;
    effect?: PolicyEffect | null;
    /**
     * Enabled
     */
    enabled?: boolean | null;
    /**
     * Params
     */
    params?: {
        [key: string]: unknown;
    } | null;
    /**
     * Priority
     */
    priority?: number | null;
    /**
     * Subject Id
     */
    subject_id?: string | null;
    subject_type?: PolicySubjectType | null;
    /**
     * Target
     */
    target?: string | null;
};
/**
 * PolicySubjectType
 *
 * The kind of subject a rule binds to.
 */
export type PolicySubjectType = 'workspace' | 'agent' | 'user' | 'group';
/**
 * PresignUploadRequest
 */
export type PresignUploadRequest = {
    /**
     * Content Type
     */
    content_type: string;
    /**
     * Filename
     */
    filename: string;
    /**
     * Sha256
     */
    sha256: string;
    /**
     * Size
     */
    size: number;
};
/**
 * PresignUploadResponse
 */
export type PresignUploadResponse = {
    /**
     * Expires In
     */
    expires_in: number;
    /**
     * Ref
     */
    ref: string;
    /**
     * Upload Url
     */
    upload_url: string;
};
/**
 * PreviewEntity
 *
 * One thing the package will (or won't) create.
 */
export type PreviewEntity = {
    /**
     * Detail
     */
    detail?: string | null;
    /**
     * Key
     */
    key: string;
    kind: EntityKind;
    /**
     * Name
     */
    name: string;
    status: EntityStatus;
};
/**
 * PreviewIssue
 *
 * A problem found while analyzing the package.
 */
export type PreviewIssue = {
    /**
     * Entity Key
     */
    entity_key?: string | null;
    /**
     * Message
     */
    message: string;
    severity: IssueSeverity;
};
/**
 * ProjectAgentRef
 */
export type ProjectAgentRef = {
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
};
/**
 * ProjectCreate
 *
 * Payload for creating a project.
 *
 * A project is a workspace-scoped container that groups skills, agents,
 * MCP server instances, and uploaded files under a shared identity and
 * optional parent project.
 */
export type ProjectCreate = {
    /**
     * Description
     *
     * Short summary of the project's purpose.
     */
    description?: string | null;
    /**
     * Instructions
     *
     * System-level instructions or notes shared across the project's agents.
     */
    instructions?: string | null;
    /**
     * Name
     *
     * Human-readable project name (unique per workspace).
     */
    name: string;
    /**
     * Parent Project Id
     *
     * UUID of the parent project, if this is a sub-project.
     */
    parent_project_id?: string | null;
};
/**
 * ProjectFileDownloadResponse
 */
export type ProjectFileDownloadResponse = {
    /**
     * Path
     */
    path: string;
    /**
     * Url
     */
    url: string;
};
/**
 * ProjectFileInfo
 */
export type ProjectFileInfo = {
    /**
     * Last Modified
     */
    last_modified?: string | null;
    /**
     * Path
     */
    path: string;
    /**
     * Size
     */
    size: number;
};
/**
 * ProjectFileListResponse
 */
export type ProjectFileListResponse = {
    /**
     * Files
     */
    files: Array<ProjectFileInfo>;
};
/**
 * ProjectMcpInstanceRef
 */
export type ProjectMcpInstanceRef = {
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
};
/**
 * ProjectResponse
 */
export type ProjectResponse = {
    /**
     * Agents
     */
    agents?: Array<ProjectAgentRef>;
    /**
     * Created By
     */
    created_by: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Instructions
     */
    instructions: string | null;
    /**
     * Mcp Instances
     */
    mcp_instances?: Array<ProjectMcpInstanceRef>;
    /**
     * Name
     */
    name: string;
    /**
     * Parent Project Id
     */
    parent_project_id: string | null;
    /**
     * Skills
     */
    skills?: Array<ProjectSkillRef>;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * ProjectSkillRef
 */
export type ProjectSkillRef = {
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
};
/**
 * ProjectUpdate
 *
 * Patch payload for a project. All fields optional — unset = unchanged.
 */
export type ProjectUpdate = {
    /**
     * Description
     *
     * New project description.
     */
    description?: string | null;
    /**
     * Instructions
     *
     * New project-level instructions.
     */
    instructions?: string | null;
    /**
     * Name
     *
     * New project name.
     */
    name?: string | null;
    /**
     * Parent Project Id
     *
     * New parent project UUID, or null to detach.
     */
    parent_project_id?: string | null;
};
/**
 * ProviderConfigCreate
 *
 * Payload for creating an LLM provider configuration.
 */
export type ProviderConfigCreate = {
    /**
     * Api Key
     *
     * Secret API key for the provider. Stored encrypted in the secret manager; never returned in responses. May be empty for proxies that accept keyless traffic — the backend suppresses the Authorization header when this is empty.
     */
    api_key?: string | null;
    /**
     * Api Key Secret Id
     *
     * Use an existing workspace secret as the API key instead of supplying one here. Mutually exclusive with api_key. The secret keeps its own lifecycle: several configurations may share it, and it cannot be deleted while any of them still points at it.
     */
    api_key_secret_id?: string | null;
    /**
     * Description
     *
     * Optional human-readable description of this configuration.
     */
    description?: string | null;
    /**
     * Endpoint Url
     *
     * Optional custom endpoint URL (e.g. for self-hosted or proxied providers). Leave unset to use the provider's default.
     */
    endpoint_url?: string | null;
    /**
     * Is Public
     *
     * If True, the configuration is visible to all workspace members; otherwise it is scoped to the creator.
     */
    is_public?: boolean;
    /**
     * Name
     *
     * Human-readable label for this provider configuration.
     */
    name: string;
    /**
     * Provider Spec Id
     *
     * UUID of the provider specification (e.g. OpenAI, Anthropic) this configuration targets. Look up via list_specs.
     */
    provider_spec_id: string;
};
/**
 * ProviderConfigResponse
 */
export type ProviderConfigResponse = {
    /**
     * Created At
     */
    created_at: string;
    /**
     * Created By
     */
    created_by: string;
    /**
     * Endpoint Url
     */
    endpoint_url: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Is Public
     */
    is_public: boolean;
    /**
     * Model Instance Ids
     */
    model_instance_ids?: Array<string>;
    /**
     * Name
     */
    name: string;
    /**
     * Provider Spec Id
     */
    provider_spec_id: string;
    /**
     * Provider Spec Key
     */
    provider_spec_key?: string | null;
    /**
     * Provider Spec Name
     */
    provider_spec_name?: string | null;
    /**
     * Updated At
     */
    updated_at: string;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * ProviderConfigUpdate
 *
 * Patch payload for an existing provider configuration. Unset = unchanged.
 */
export type ProviderConfigUpdate = {
    /**
     * Api Key
     *
     * New API key. Replaces the previously stored secret. Send an empty string to clear the key for keyless custom endpoints.
     */
    api_key?: string | null;
    /**
     * Api Key Secret Id
     *
     * Point this configuration at an existing workspace secret instead. Mutually exclusive with api_key.
     */
    api_key_secret_id?: string | null;
    /**
     * Description
     *
     * New description for the configuration.
     */
    description?: string | null;
    /**
     * Endpoint Url
     *
     * New endpoint URL, or empty string to clear.
     */
    endpoint_url?: string | null;
    /**
     * Is Active
     *
     * Activate or deactivate the configuration.
     */
    is_active?: boolean | null;
    /**
     * Is Public
     *
     * Toggle workspace-wide visibility.
     */
    is_public?: boolean | null;
    /**
     * Name
     *
     * New human-readable label for the configuration.
     */
    name?: string | null;
};
/**
 * ProviderSpecResponse
 */
export type ProviderSpecResponse = {
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Icon
     */
    icon: string | null;
    /**
     * Icon Url
     */
    icon_url: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Builtin
     */
    is_builtin: boolean;
    /**
     * Name
     */
    name: string;
    /**
     * Provider Key
     */
    provider_key: string;
    /**
     * Provider Type
     */
    provider_type: string;
    /**
     * Updated At
     */
    updated_at: string;
};
/**
 * ProviderSpecWithModelsResponse
 */
export type ProviderSpecWithModelsResponse = {
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Icon
     */
    icon: string | null;
    /**
     * Icon Url
     */
    icon_url: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Builtin
     */
    is_builtin: boolean;
    /**
     * Models
     */
    models: Array<AgentareaApiApiV1ProviderSpecsModelSpecResponse>;
    /**
     * Name
     */
    name: string;
    /**
     * Provider Key
     */
    provider_key: string;
    /**
     * Provider Type
     */
    provider_type: string;
    /**
     * Updated At
     */
    updated_at: string;
};
/**
 * RegistryCreate
 */
export type RegistryCreate = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Name
     *
     * Human-readable registry name
     */
    name: string;
    /**
     * Registry Type
     *
     * Entity type: 'mcp_servers' or 'skills'
     */
    registry_type: string;
    /**
     * Source Type
     *
     * Fetch method: 'url', 'github', or 'api'
     */
    source_type: string;
    /**
     * Source Url
     *
     * URL to the registry source (JSON or YAML)
     */
    source_url: string;
    /**
     * Sync Mode
     *
     * 'auto' or 'manual'
     */
    sync_mode?: string;
};
/**
 * RegistryItemResponse
 */
export type RegistryItemResponse = {
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * External Id
     */
    external_id: string;
    /**
     * Id
     */
    id: string;
    /**
     * Installed Entity Id
     */
    installed_entity_id: string | null;
    /**
     * Installed Version
     */
    installed_version: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Registry Id
     */
    registry_id: string;
    /**
     * Spec
     */
    spec: {
        [key: string]: unknown;
    };
    /**
     * Tags
     */
    tags: Array<string>;
    /**
     * Update Available
     */
    update_available: boolean;
    /**
     * Updated At
     */
    updated_at: string;
    /**
     * Version
     */
    version: string | null;
};
/**
 * RegistryResponse
 */
export type RegistryResponse = {
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Item Count
     */
    item_count: number;
    /**
     * Last Sync Error
     */
    last_sync_error: string | null;
    /**
     * Last Synced At
     */
    last_synced_at: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Registry Type
     */
    registry_type: string;
    /**
     * Source Type
     */
    source_type: string;
    /**
     * Source Url
     */
    source_url: string;
    /**
     * Sync Mode
     */
    sync_mode: string;
    /**
     * Updated At
     */
    updated_at: string;
};
/**
 * RegistryUpdate
 */
export type RegistryUpdate = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Is Active
     */
    is_active?: boolean | null;
    /**
     * Name
     */
    name?: string | null;
    /**
     * Source Url
     */
    source_url?: string | null;
    /**
     * Sync Mode
     */
    sync_mode?: string | null;
};
/**
 * RelationshipItem
 */
export type RelationshipItem = {
    /**
     * Direct
     */
    direct: boolean;
    /**
     * Fanout
     */
    fanout?: number | null;
    /**
     * Namespace
     */
    namespace: string;
    /**
     * Object
     */
    object: string;
    /**
     * Object Name
     */
    object_name: string;
    /**
     * Relation
     */
    relation: string;
    /**
     * Subject
     */
    subject: string;
    /**
     * Subject Kind
     */
    subject_kind: 'agent' | 'user' | 'workspace';
    /**
     * Subject Name
     */
    subject_name: string;
};
/**
 * RelationshipWriteRequest
 */
export type RelationshipWriteRequest = {
    /**
     * Namespace
     */
    namespace: string;
    /**
     * Object
     */
    object: string;
    /**
     * Relation
     */
    relation: string;
    /**
     * Subject Id
     */
    subject_id?: string | null;
    subject_set?: SubjectSetBody | null;
};
/**
 * RelationshipsResponse
 */
export type RelationshipsResponse = {
    /**
     * Count
     */
    count: number;
    /**
     * Relationships
     */
    relationships: Array<RelationshipItem>;
};
/**
 * ResolveHop
 */
export type ResolveHop = {
    /**
     * Color
     */
    color: string;
    /**
     * Id
     */
    id: string;
    /**
     * Kind
     */
    kind: string;
    /**
     * Name
     */
    name: string;
};
/**
 * ResolvePath
 */
export type ResolvePath = {
    /**
     * Hops
     */
    hops: Array<ResolveHop>;
    /**
     * Relation
     */
    relation: string;
    /**
     * Rels
     */
    rels: Array<string>;
};
/**
 * ResolveRequest
 */
export type ResolveRequest = {
    /**
     * Resource Id
     */
    resource_id: string;
    /**
     * Resource Kind
     */
    resource_kind: 'skill' | 'collection' | 'mcp' | 'agent';
    /**
     * Subject Id
     */
    subject_id: string;
};
/**
 * ResolveResponse
 */
export type ResolveResponse = {
    /**
     * Allowed
     */
    allowed: boolean;
    /**
     * Effective Relation
     */
    effective_relation: string | null;
    /**
     * Paths
     */
    paths: Array<ResolvePath>;
    /**
     * Verb
     */
    verb: string;
};
/**
 * RunExecutionConfig
 *
 * Caller-requested execution ceiling; governance may only tighten it.
 */
export type RunExecutionConfig = {
    /**
     * Max Model Turns
     *
     * Maximum LLM/model turns requested for this run.
     */
    max_model_turns: number;
};
/**
 * SandboxFileItem
 */
export type SandboxFileItem = {
    /**
     * Path
     */
    path: string;
};
/**
 * SandboxFileListResponse
 */
export type SandboxFileListResponse = {
    /**
     * Items
     */
    items: Array<SandboxFileItem>;
    /**
     * Total
     */
    total: number;
};
/**
 * SandboxListResponse
 */
export type SandboxListResponse = {
    /**
     * Items
     */
    items: Array<SandboxSummary>;
    /**
     * Total
     */
    total: number;
};
/**
 * SandboxResources
 */
export type SandboxResources = {
    /**
     * Cpu
     */
    cpu: string;
    /**
     * Memory
     */
    memory: string;
};
/**
 * SandboxSummary
 */
export type SandboxSummary = {
    /**
     * Created At
     */
    created_at: string;
    /**
     * Expires At
     */
    expires_at: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Isolation
     */
    isolation: string;
    /**
     * Provider
     */
    provider: string;
    resources: SandboxResources;
    /**
     * State
     */
    state: string;
    /**
     * Task Id
     */
    task_id: string;
};
/**
 * SecretConsumer
 */
export type SecretConsumer = {
    /**
     * Consumer Id
     *
     * Id of the using entity.
     */
    consumer_id: string;
    /**
     * Consumer Type
     *
     * Kind of thing using the secret, e.g. provider_config.
     */
    consumer_type: string;
    /**
     * Field
     *
     * Which slot on that entity — a header name, an env var.
     */
    field: string;
};
/**
 * SecretCreate
 */
export type SecretCreate = {
    /**
     * Description
     */
    description?: string | null;
    /**
     * Name
     *
     * 2-64 characters: lowercase letters, digits, '-' and '_', starting and ending with a letter or digit. Prefixes the platform uses for its own secrets are rejected.
     */
    name: string;
    /**
     * Value
     *
     * Stored encrypted; never returned.
     */
    value: string;
};
/**
 * SecretDescriptionUpdate
 */
export type SecretDescriptionUpdate = {
    /**
     * Description
     */
    description?: string | null;
};
/**
 * SecretResponse
 *
 * A secret's metadata. The value is never part of this.
 */
export type SecretResponse = {
    /**
     * Created At
     */
    created_at?: string | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Name
     *
     * Unique within the workspace.
     */
    name: string;
    /**
     * Updated At
     */
    updated_at?: string | null;
    /**
     * Used By
     */
    used_by?: Array<SecretConsumer>;
};
/**
 * SecretValueUpdate
 */
export type SecretValueUpdate = {
    /**
     * Value
     *
     * Replaces the stored value.
     */
    value: string;
};
/**
 * SetupField
 *
 * A single value the user must provide before the package can run.
 *
 * This is the generalized analogue of a Claude plugin ``userConfig`` entry
 * and mirrors the existing MCP ``env_schema`` (KeyValueInput) shape.
 */
export type SetupField = {
    /**
     * Default
     */
    default?: unknown | null;
    /**
     * Help
     *
     * Help text shown beneath the field.
     */
    help?: string | null;
    /**
     * Key
     *
     * Stable identifier referenced via ${setup.key}.
     */
    key: string;
    /**
     * Label
     *
     * Human-readable label rendered in the form.
     */
    label: string;
    /**
     * Max
     *
     * Upper bound for type='number'.
     */
    max?: number | null;
    /**
     * Min
     *
     * Lower bound for type='number'.
     */
    min?: number | null;
    /**
     * Options
     *
     * Choices for type='select'.
     */
    options?: Array<string> | null;
    /**
     * Required
     */
    required?: boolean;
    type?: SetupFieldType;
};
/**
 * SetupFieldType
 *
 * Input widget / storage hint for a setup field.
 */
export type SetupFieldType = 'secret' | 'string' | 'number' | 'boolean' | 'select';
/**
 * SkillContentResponse
 *
 * Skill content response model.
 */
export type SkillContentResponse = {
    /**
     * Content
     */
    content: string;
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
};
/**
 * SkillCreateRequest
 *
 * Request to create a skill.
 */
export type SkillCreateRequest = {
    /**
     * Content
     *
     * Raw markdown content
     */
    content?: string | null;
    /**
     * Description
     *
     * Optional description override
     */
    description?: string | null;
    /**
     * Github Url
     *
     * GitHub repository URL
     */
    github_url?: string | null;
    /**
     * Name
     *
     * Optional name override
     */
    name?: string | null;
};
/**
 * SkillFileResponse
 *
 * Skill file info response model.
 */
export type SkillFileResponse = {
    /**
     * Path
     */
    path: string;
    /**
     * Size
     */
    size: number;
    /**
     * Url
     */
    url?: string | null;
};
/**
 * SkillFilesResponse
 *
 * Skill files list response model.
 */
export type SkillFilesResponse = {
    /**
     * Files
     */
    files: Array<SkillFileResponse>;
    /**
     * Skill Id
     */
    skill_id: string;
};
/**
 * SkillMemberAddRequest
 *
 * Request to add a child skill member.
 */
export type SkillMemberAddRequest = {
    /**
     * Child Skill Id
     *
     * ID of the child skill to add
     */
    child_skill_id: string;
    /**
     * Dependencies
     *
     * IDs of sibling children that must run before this one
     */
    dependencies?: Array<string>;
    /**
     * Is Required
     *
     * Whether this child is required
     */
    is_required?: boolean;
    /**
     * Order
     *
     * Execution order hint
     */
    order?: number;
};
/**
 * SkillMemberResponse
 *
 * Skill member response model.
 */
export type SkillMemberResponse = {
    /**
     * Child Skill Id
     */
    child_skill_id: string;
    /**
     * Dependencies
     */
    dependencies: Array<string>;
    /**
     * Is Required
     */
    is_required: boolean;
    /**
     * Order
     */
    order: number;
    /**
     * Parent Skill Id
     */
    parent_skill_id: string;
};
/**
 * SkillRef
 */
export type SkillRef = {
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
};
/**
 * SkillResponse
 *
 * Skill response model.
 */
export type SkillResponse = {
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Is Catalog
     */
    is_catalog?: boolean;
    /**
     * Name
     */
    name: string;
    /**
     * Network Scope
     */
    network_scope: string;
    /**
     * Registry Item Id
     */
    registry_item_id?: string | null;
    /**
     * Slug
     */
    slug: string;
    /**
     * Source Type
     */
    source_type: string;
    /**
     * Source Url
     */
    source_url: string | null;
    /**
     * Update Available
     */
    update_available?: boolean;
    /**
     * Updated At
     */
    updated_at: string;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * SkillUpdateRequest
 *
 * Request to update a skill.
 */
export type SkillUpdateRequest = {
    /**
     * Content
     *
     * New content (only for content-type skills)
     */
    content?: string | null;
    /**
     * Description
     *
     * New description
     */
    description?: string | null;
    /**
     * Name
     *
     * New name
     */
    name?: string | null;
};
/**
 * SourceProjectBody
 */
export type SourceProjectBody = {
    /**
     * Project Id
     */
    project_id?: string | null;
};
/**
 * SpecPreviewRequest
 */
export type SpecPreviewRequest = {
    /**
     * Spec Content
     */
    spec_content?: {
        [key: string]: unknown;
    } | null;
    /**
     * Spec Url
     */
    spec_url?: string | null;
};
/**
 * SpecPreviewResponse
 */
export type SpecPreviewResponse = {
    /**
     * Base Url
     */
    base_url?: string | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Title
     */
    title?: string | null;
    /**
     * Tools
     */
    tools?: Array<{
        [key: string]: string;
    }>;
    /**
     * Version
     */
    version?: string | null;
};
/**
 * SpendCard
 */
export type SpendCard = {
    /**
     * Cap Usd
     */
    cap_usd: number | null;
    /**
     * Mtd Usd
     */
    mtd_usd: number;
    /**
     * Pct Of Cap
     */
    pct_of_cap: number | null;
    /**
     * Projected Eom Usd
     */
    projected_eom_usd: number | null;
    /**
     * Projection Method
     */
    projection_method?: string;
    /**
     * Today Usd
     */
    today_usd: number;
};
/**
 * SubjectSetBody
 */
export type SubjectSetBody = {
    /**
     * Namespace
     */
    namespace: string;
    /**
     * Object
     */
    object: string;
    /**
     * Relation
     */
    relation: string;
};
/**
 * TaskArtifactItem
 *
 * A file explicitly published from a live task sandbox.
 */
export type TaskArtifactItem = {
    /**
     * Content Type
     */
    content_type: string | null;
    /**
     * Created At
     */
    created_at: string | null;
    /**
     * Download Url
     */
    download_url: string;
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
    /**
     * Path
     */
    path: string;
    /**
     * Sha256
     */
    sha256: string | null;
    /**
     * Size
     */
    size: number;
};
/**
 * TaskCommandPayload
 */
export type TaskCommandPayload = {
    /**
     * Budget Usd
     */
    budget_usd?: number | string | null;
    /**
     * Command
     */
    command: string;
    /**
     * Message
     */
    message?: string | null;
    /**
     * Message Id
     */
    message_id?: string | null;
    /**
     * Model Instance Id
     */
    model_instance_id?: string | null;
};
/**
 * TaskCreate
 */
export type TaskCreate = {
    /**
     * Attachments
     */
    attachments?: Array<string> | null;
    /**
     * Description
     */
    description: string;
    execution?: RunExecutionConfig | null;
    /**
     * Parameters
     */
    parameters?: {
        [key: string]: unknown;
    };
    /**
     * Project Id
     */
    project_id?: string | null;
    /**
     * Requires Human Approval
     */
    requires_human_approval?: boolean | null;
    task_policy?: PolicyDocument | null;
};
/**
 * TaskEvent
 *
 * Model for task execution events.
 */
export type TaskEvent = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Event Type
     */
    event_type: string;
    /**
     * Execution Id
     */
    execution_id: string;
    /**
     * Id
     */
    id: string;
    /**
     * Message
     */
    message: string;
    /**
     * Metadata
     */
    metadata?: {
        [key: string]: unknown;
    };
    /**
     * Task Id
     */
    task_id: string;
    /**
     * Timestamp
     */
    timestamp: string;
};
/**
 * TaskEventResponse
 *
 * Response model for paginated task events.
 */
export type TaskEventResponse = {
    /**
     * Events
     */
    events: Array<TaskEvent>;
    /**
     * Has Next
     */
    has_next: boolean;
    /**
     * Page
     */
    page: number;
    /**
     * Page Size
     */
    page_size: number;
    /**
     * Total
     */
    total: number;
};
/**
 * TaskInputSubmission
 *
 * Structured user input submission for a pending workflow input request.
 */
export type TaskInputSubmission = {
    /**
     * Answers
     */
    answers?: {
        [key: string]: unknown;
    };
    /**
     * Input Request Id
     */
    input_request_id: string;
    /**
     * Secrets
     */
    secrets?: {
        [key: string]: string | InputSecretValue;
    };
};
/**
 * TaskResponse
 */
export type TaskResponse = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string;
    /**
     * Error
     */
    error?: string | null;
    /**
     * Execution Id
     */
    execution_id?: string | null;
    /**
     * Failure Reason
     */
    failure_reason?: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Parameters
     */
    parameters: {
        [key: string]: unknown;
    };
    /**
     * Result
     */
    result?: {
        [key: string]: unknown;
    } | string | null;
    /**
     * Status
     */
    status: string;
    /**
     * Total Cost
     */
    total_cost?: number | null;
};
/**
 * TaskSummary
 *
 * Headline rollup for a single task, derived from the event log.
 *
 * Backed by the ``task_summary`` Postgres view. Stable contract — when
 * the view's implementation moves to a materialized view or projection
 * table, this shape stays the same. Per-tool breakdowns and per-artifact
 * lists are deliberately not here; they live in their own endpoints so
 * this stays small and additive.
 */
export type TaskSummary = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Cost Usd
     */
    cost_usd?: number;
    /**
     * Delegations Completed
     */
    delegations_completed?: number;
    /**
     * Delegations Failed
     */
    delegations_failed?: number;
    /**
     * Delegations Started
     */
    delegations_started?: number;
    /**
     * Duration Ms
     */
    duration_ms?: number | null;
    /**
     * Ended At
     */
    ended_at?: string | null;
    /**
     * Final Response
     */
    final_response?: string | null;
    /**
     * Iterations
     */
    iterations?: number;
    /**
     * Last Error
     */
    last_error?: string | null;
    /**
     * Llm Calls
     */
    llm_calls?: number;
    /**
     * Llm Calls Failed
     */
    llm_calls_failed?: number;
    /**
     * Started At
     */
    started_at?: string | null;
    /**
     * Status
     */
    status: string;
    /**
     * Task Id
     */
    task_id: string;
    /**
     * Tools Called
     */
    tools_called?: number;
    /**
     * Tools Failed
     */
    tools_failed?: number;
    /**
     * Workspace Id
     */
    workspace_id: string;
};
/**
 * TaskWithAgent
 *
 * Task response with agent information for global task listing.
 */
export type TaskWithAgent = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Agent Name
     */
    agent_name: string;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string;
    /**
     * Error
     */
    error?: string | null;
    /**
     * Escalation Id
     */
    escalation_id?: string | null;
    /**
     * Escalation Tool Name
     */
    escalation_tool_name?: string | null;
    /**
     * Execution Id
     */
    execution_id?: string | null;
    /**
     * Failure Reason
     */
    failure_reason?: string | null;
    /**
     * Id
     */
    id: string;
    /**
     * Parameters
     */
    parameters: {
        [key: string]: unknown;
    };
    /**
     * Result
     */
    result?: {
        [key: string]: unknown;
    } | string | null;
    /**
     * Status
     */
    status: string;
    /**
     * Total Cost
     */
    total_cost?: number | null;
};
/**
 * TokenPolicy
 *
 * Token-related ceilings.
 */
export type TokenPolicy = {
    /**
     * Max Tokens
     */
    max_tokens?: number | null;
    /**
     * Max Tokens Per Call
     */
    max_tokens_per_call?: number | null;
};
/**
 * ToolResponse
 *
 * Unified tool response format.
 */
export type ToolResponse = {
    /**
     * Description
     */
    description: string;
    /**
     * Input Schema
     */
    input_schema: {
        [key: string]: unknown;
    };
    /**
     * Mcp Instance Id
     */
    mcp_instance_id?: string | null;
    /**
     * Mcp Instance Name
     */
    mcp_instance_name?: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Type
     */
    type: 'code' | 'mcp';
};
/**
 * ToolsPolicy
 *
 * MCP tool capability restrictions.
 */
export type ToolsPolicy = {
    /**
     * Allowed
     */
    allowed?: Array<string> | null;
    /**
     * Denied
     */
    denied?: Array<string>;
};
/**
 * TriggerCreate
 *
 * Payload for creating a trigger.
 *
 * A trigger fires an agent — either on a cron schedule (``trigger_type='cron'``)
 * or in response to an inbound webhook (``trigger_type='webhook'``). For poll-based
 * channels (e.g. email inbox), use ``trigger_type='polling'`` plus a
 * ``data_extractor`` configuration.
 */
export type TriggerCreate = {
    /**
     * Agent Id
     *
     * UUID of the agent to invoke when the trigger fires.
     */
    agent_id: string;
    /**
     * Allowed Methods
     *
     * HTTP methods accepted on the webhook endpoint.
     */
    allowed_methods?: Array<string>;
    /**
     * Channel Credentials
     *
     * Channel credentials (bot_token, SMTP password, etc). Stored encrypted in the secret store. Never returned in responses.
     */
    channel_credentials?: {
        [key: string]: unknown;
    } | null;
    /**
     * Conditions
     *
     * Optional conditions evaluated against event data before firing.
     */
    conditions?: {
        [key: string]: unknown;
    };
    /**
     * Cron Expression
     *
     * 5- or 6-field cron expression (required when trigger_type='cron').
     */
    cron_expression?: string | null;
    /**
     * Data Extractor
     *
     * Polling extractor identifier (e.g. 'imap', 'rss').
     */
    data_extractor?: string | null;
    /**
     * Data Extractor Config
     *
     * Connection/auth details for the polling extractor.
     */
    data_extractor_config?: {
        [key: string]: unknown;
    } | null;
    /**
     * Description
     *
     * Short summary of what this trigger does.
     */
    description?: string;
    /**
     * Enabled
     *
     * Whether the trigger is active immediately on creation.
     */
    enabled?: boolean;
    /**
     * Event Types
     *
     * Event types to filter on (empty list = accept all events).
     */
    event_types?: Array<string>;
    /**
     * Failure Threshold
     *
     * Auto-disable after this many consecutive failed executions.
     */
    failure_threshold?: number;
    /**
     * Name
     *
     * Human-readable trigger name.
     */
    name: string;
    /**
     * Task Parameters
     *
     * Parameters merged into the task created when the trigger fires.
     */
    task_parameters?: {
        [key: string]: unknown;
    };
    /**
     * Timezone
     *
     * IANA timezone for cron evaluation (e.g. 'UTC', 'America/New_York').
     */
    timezone?: string;
    /**
     * Trigger Type
     *
     * 'cron' for scheduled, 'webhook' for inbound HTTP, 'polling' for extractor-driven.
     */
    trigger_type: 'cron' | 'webhook' | 'polling';
    /**
     * Validation Rules
     *
     * Per-channel validation rules (signature secrets, allowed senders, etc).
     */
    validation_rules?: {
        [key: string]: unknown;
    };
    /**
     * Webhook Config
     *
     * Channel-specific configuration (bot tokens, signing keys, etc).
     */
    webhook_config?: {
        [key: string]: unknown;
    } | null;
    /**
     * Webhook Id
     *
     * Public webhook path segment. Auto-generated if omitted for webhook triggers.
     */
    webhook_id?: string | null;
    /**
     * Webhook Type
     *
     * Channel type: 'generic', 'telegram', 'slack', 'discord', etc.
     */
    webhook_type?: string;
};
/**
 * TriggerExecuteRequest
 *
 * Request model for executing a trigger via the event service.
 */
export type TriggerExecuteRequest = {
    /**
     * Channel Origin
     */
    channel_origin?: {
        [key: string]: unknown;
    };
    /**
     * Events
     */
    events?: Array<{
        [key: string]: unknown;
    }>;
};
/**
 * TriggerExecutionResponse
 *
 * Response model for trigger execution data.
 */
export type TriggerExecutionResponse = {
    /**
     * Error Message
     */
    error_message?: string | null;
    /**
     * Executed At
     */
    executed_at: string;
    /**
     * Execution Time Ms
     */
    execution_time_ms: number;
    /**
     * Id
     */
    id: string;
    /**
     * Run Id
     */
    run_id?: string | null;
    /**
     * Status
     */
    status: string;
    /**
     * Task Id
     */
    task_id?: string | null;
    /**
     * Trigger Data
     */
    trigger_data: {
        [key: string]: unknown;
    };
    /**
     * Trigger Id
     */
    trigger_id: string;
    /**
     * Workflow Id
     */
    workflow_id?: string | null;
};
/**
 * TriggerResponse
 *
 * Response model for trigger data.
 */
export type TriggerResponse = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Allowed Methods
     */
    allowed_methods?: Array<string> | null;
    /**
     * Conditions
     */
    conditions: {
        [key: string]: unknown;
    };
    /**
     * Consecutive Failures
     */
    consecutive_failures: number;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Created By
     */
    created_by: string;
    /**
     * Cron Expression
     */
    cron_expression?: string | null;
    /**
     * Data Extractor
     */
    data_extractor?: string | null;
    /**
     * Description
     */
    description: string;
    /**
     * Event Types
     */
    event_types?: Array<string>;
    /**
     * Failure Threshold
     */
    failure_threshold: number;
    /**
     * Has Channel Credentials
     */
    has_channel_credentials?: boolean;
    /**
     * Id
     */
    id: string;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Last Execution At
     */
    last_execution_at?: string | null;
    /**
     * Name
     */
    name: string;
    /**
     * Next Run Time
     */
    next_run_time?: string | null;
    /**
     * Task Parameters
     */
    task_parameters: {
        [key: string]: unknown;
    };
    /**
     * Timezone
     */
    timezone?: string | null;
    /**
     * Trigger Type
     */
    trigger_type: string;
    /**
     * Updated At
     */
    updated_at: string;
    /**
     * Validation Rules
     */
    validation_rules?: {
        [key: string]: unknown;
    } | null;
    /**
     * Webhook Config
     */
    webhook_config?: {
        [key: string]: unknown;
    } | null;
    /**
     * Webhook Id
     */
    webhook_id?: string | null;
    /**
     * Webhook Type
     */
    webhook_type?: string | null;
};
/**
 * TriggerStatusResponse
 *
 * Response model for trigger status information.
 */
export type TriggerStatusResponse = {
    /**
     * Consecutive Failures
     */
    consecutive_failures: number;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Last Execution At
     */
    last_execution_at?: string | null;
    /**
     * Schedule Info
     */
    schedule_info?: {
        [key: string]: unknown;
    } | null;
    /**
     * Should Disable Due To Failures
     */
    should_disable_due_to_failures: boolean;
    /**
     * Trigger Id
     */
    trigger_id: string;
};
/**
 * TriggerUpdate
 *
 * Patch payload for a trigger. All fields optional — unset = unchanged.
 */
export type TriggerUpdate = {
    /**
     * Allowed Methods
     */
    allowed_methods?: Array<string> | null;
    /**
     * Channel Credentials
     *
     * Channel credentials to update. Pass to rotate credentials.
     */
    channel_credentials?: {
        [key: string]: unknown;
    } | null;
    /**
     * Conditions
     */
    conditions?: {
        [key: string]: unknown;
    } | null;
    /**
     * Cron Expression
     */
    cron_expression?: string | null;
    /**
     * Description
     */
    description?: string | null;
    /**
     * Enabled
     *
     * Toggle the trigger active state. Maps to ``is_active`` server-side. REST clients may pass either ``enabled`` (canonical) or ``is_active`` (alias).
     */
    enabled?: boolean | null;
    /**
     * Failure Threshold
     */
    failure_threshold?: number | null;
    /**
     * Name
     */
    name?: string | null;
    /**
     * Task Parameters
     */
    task_parameters?: {
        [key: string]: unknown;
    } | null;
    /**
     * Timezone
     */
    timezone?: string | null;
    /**
     * Validation Rules
     */
    validation_rules?: {
        [key: string]: unknown;
    } | null;
    /**
     * Webhook Config
     */
    webhook_config?: {
        [key: string]: unknown;
    } | null;
    /**
     * Webhook Type
     */
    webhook_type?: string | null;
};
/**
 * UpcomingItem
 */
export type UpcomingItem = {
    /**
     * Cron Expression
     */
    cron_expression?: string | null;
    /**
     * Fires At
     */
    fires_at: string;
    /**
     * Kind
     */
    kind: string;
    /**
     * Task Id
     */
    task_id?: string | null;
    /**
     * Title
     */
    title: string;
    /**
     * Trigger Id
     */
    trigger_id?: string | null;
};
/**
 * UpdateAllResponse
 */
export type UpdateAllResponse = {
    /**
     * Errors
     */
    errors: number;
    /**
     * Updated
     */
    updated: number;
};
/**
 * UpdateWalletRequest
 */
export type UpdateWalletRequest = {
    credentials?: WalletCredentialsSchema | null;
    mpp_config?: MppConfigSchema | null;
    /**
     * Service Budget Period
     */
    service_budget_period?: string | null;
    /**
     * Service Budget Usd
     */
    service_budget_usd?: number | null;
    /**
     * Status
     */
    status?: string | null;
    /**
     * Wallet Type
     */
    wallet_type?: string | null;
    x402_config?: X402ConfigSchema | null;
};
/**
 * ValidateRequest
 */
export type ValidateRequest = {
    /**
     * Endpoint Url
     *
     * For type=url: the MCP endpoint URL
     */
    endpoint_url?: string | null;
    /**
     * Headers
     */
    headers?: {
        [key: string]: string;
    };
    /**
     * Name
     */
    name?: string | null;
    /**
     * Type
     *
     * Instance type: url, docker, command
     */
    type: string;
};
/**
 * ValidationError
 */
export type ValidationError = {
    /**
     * Context
     */
    ctx?: {
        [key: string]: unknown;
    };
    /**
     * Input
     */
    input?: unknown;
    /**
     * Location
     */
    loc: Array<string | number>;
    /**
     * Message
     */
    msg: string;
    /**
     * Error Type
     */
    type: string;
};
/**
 * WalletBalanceResponse
 */
export type WalletBalanceResponse = {
    /**
     * Remaining
     */
    remaining: number;
    /**
     * Service Budget Period
     */
    service_budget_period: string;
    /**
     * Service Budget Usd
     */
    service_budget_usd: number;
    /**
     * Total Spent Current Period
     */
    total_spent_current_period: number;
};
/**
 * WalletCredentialsSchema
 */
export type WalletCredentialsSchema = {
    /**
     * Mpp Tempo Key
     */
    mpp_tempo_key?: string | null;
    /**
     * X402 Private Key
     */
    x402_private_key?: string | null;
};
/**
 * WalletExhaustedBlocker
 */
export type WalletExhaustedBlocker = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Agent Name
     */
    agent_name: string;
    /**
     * Budget Usd
     */
    budget_usd: number;
    /**
     * Period
     */
    period: string;
};
/**
 * WalletResponse
 */
export type WalletResponse = {
    /**
     * Agent Id
     */
    agent_id: string;
    /**
     * Created At
     */
    created_at?: string | null;
    /**
     * Has Credentials
     */
    has_credentials?: boolean;
    /**
     * Id
     */
    id: string;
    /**
     * Mpp Config
     */
    mpp_config?: {
        [key: string]: unknown;
    } | null;
    /**
     * Service Budget Period
     */
    service_budget_period: string;
    /**
     * Service Budget Usd
     */
    service_budget_usd: number;
    /**
     * Status
     */
    status: string;
    /**
     * Updated At
     */
    updated_at?: string | null;
    /**
     * Wallet Type
     */
    wallet_type: string;
    /**
     * X402 Config
     */
    x402_config?: {
        [key: string]: unknown;
    } | null;
};
/**
 * WorkspaceFileDownloadResponse
 */
export type WorkspaceFileDownloadResponse = {
    /**
     * Path
     */
    path: string;
    /**
     * Url
     */
    url: string;
};
/**
 * WorkspaceFileInfo
 */
export type WorkspaceFileInfo = {
    /**
     * Content Type
     */
    content_type?: string | null;
    /**
     * Last Modified
     */
    last_modified?: string | null;
    /**
     * Path
     */
    path: string;
    /**
     * Size
     */
    size: number;
};
/**
 * WorkspaceFileListResponse
 */
export type WorkspaceFileListResponse = {
    /**
     * Directories
     */
    directories?: Array<string>;
    /**
     * Files
     */
    files: Array<WorkspaceFileInfo>;
};
/**
 * WorkspaceResponse
 */
export type WorkspaceResponse = {
    /**
     * Id
     */
    id: string;
    /**
     * Name
     */
    name: string;
    /**
     * Slug
     */
    slug: string;
    /**
     * Type
     */
    type: string;
};
/**
 * WorkspaceSettingsResponse
 */
export type WorkspaceSettingsResponse = {
    /**
     * Monthly Cap Usd
     */
    monthly_cap_usd: number | null;
};
/**
 * WorkspaceSettingsUpdate
 */
export type WorkspaceSettingsUpdate = {
    /**
     * Monthly Cap Usd
     */
    monthly_cap_usd: number | null;
};
/**
 * X402ConfigSchema
 */
export type X402ConfigSchema = {
    /**
     * Facilitator Url
     */
    facilitator_url?: string;
    /**
     * Network
     */
    network?: string;
    /**
     * Scheme
     */
    scheme?: string;
    /**
     * Signer Type
     */
    signer_type?: string;
};
/**
 * SyncResponse
 */
export type AgentareaApiApiV1AccessControlSyncResponse = {
    /**
     * Collections
     */
    collections: number;
    /**
     * Written
     */
    written: number;
};
/**
 * ModelSpecResponse
 */
export type AgentareaApiApiV1ModelSpecsModelSpecResponse = {
    /**
     * Context Window
     */
    context_window: number;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Default Context Strategy
     */
    default_context_strategy: string | null;
    /**
     * Description
     */
    description: string | null;
    /**
     * Display Name
     */
    display_name: string;
    /**
     * Id
     */
    id: string;
    /**
     * Input Cost Per Token
     */
    input_cost_per_token?: number | null;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Max Output Tokens
     */
    max_output_tokens?: number | null;
    /**
     * Model Name
     */
    model_name: string;
    /**
     * Output Cost Per Token
     */
    output_cost_per_token?: number | null;
    /**
     * Provider Key
     */
    provider_key?: string | null;
    /**
     * Provider Name
     */
    provider_name?: string | null;
    /**
     * Provider Spec Id
     */
    provider_spec_id: string;
    /**
     * Supports Function Calling
     */
    supports_function_calling?: boolean | null;
    /**
     * Supports Reasoning
     */
    supports_reasoning?: boolean | null;
    /**
     * Supports Vision
     */
    supports_vision?: boolean | null;
    /**
     * Updated At
     */
    updated_at: string;
};
/**
 * ModelSpecResponse
 */
export type AgentareaApiApiV1ProviderSpecsModelSpecResponse = {
    /**
     * Context Window
     */
    context_window: number;
    /**
     * Created At
     */
    created_at: string;
    /**
     * Description
     */
    description: string | null;
    /**
     * Display Name
     */
    display_name: string;
    /**
     * Id
     */
    id: string;
    /**
     * Input Cost Per Token
     */
    input_cost_per_token?: number | null;
    /**
     * Is Active
     */
    is_active: boolean;
    /**
     * Max Output Tokens
     */
    max_output_tokens?: number | null;
    /**
     * Model Name
     */
    model_name: string;
    /**
     * Output Cost Per Token
     */
    output_cost_per_token?: number | null;
    /**
     * Provider Spec Id
     */
    provider_spec_id: string;
    /**
     * Supports Function Calling
     */
    supports_function_calling?: boolean | null;
    /**
     * Supports Reasoning
     */
    supports_reasoning?: boolean | null;
    /**
     * Supports Vision
     */
    supports_vision?: boolean | null;
    /**
     * Updated At
     */
    updated_at: string;
};
/**
 * SyncResponse
 */
export type AgentareaApiApiV1RegistriesSyncResponse = {
    /**
     * New Specs
     */
    new_specs: number;
    /**
     * Total
     */
    total: number;
    /**
     * Unchanged
     */
    unchanged: number;
    /**
     * Updates Flagged
     */
    updates_flagged: number;
};
export type HydraJwksProxyWellKnownJwksJsonGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/.well-known/jwks.json';
};
export type HydraJwksProxyWellKnownJwksJsonGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type OauthAuthorizationServerMetadataWellKnownOauthAuthorizationServerGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/.well-known/oauth-authorization-server';
};
export type OauthAuthorizationServerMetadataWellKnownOauthAuthorizationServerGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type OauthProtectedResourceMetadataWellKnownOauthProtectedResourceGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/.well-known/oauth-protected-resource';
};
export type OauthProtectedResourceMetadataWellKnownOauthProtectedResourceGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type OauthProtectedResourceMetadataByPathWellKnownOauthProtectedResourceResourcePathGetData = {
    body?: never;
    path: {
        /**
         * Resource Path
         */
        resource_path: string;
    };
    query?: never;
    url: '/.well-known/oauth-protected-resource/{resource_path}';
};
export type OauthProtectedResourceMetadataByPathWellKnownOauthProtectedResourceResourcePathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type OauthProtectedResourceMetadataByPathWellKnownOauthProtectedResourceResourcePathGetError = OauthProtectedResourceMetadataByPathWellKnownOauthProtectedResourceResourcePathGetErrors[keyof OauthProtectedResourceMetadataByPathWellKnownOauthProtectedResourceResourcePathGetErrors];
export type OauthProtectedResourceMetadataByPathWellKnownOauthProtectedResourceResourcePathGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HealthHealthGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/health';
};
export type HealthHealthGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HydraAuthRedirectOauth2AuthGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/oauth2/auth';
};
export type HydraAuthRedirectOauth2AuthGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HydraDcrProxyOauth2RegisterPostData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/oauth2/register';
};
export type HydraDcrProxyOauth2RegisterPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HydraOauth2ProxyOauth2PathDeleteData = {
    body?: never;
    path: {
        /**
         * Path
         */
        path: string;
    };
    query?: never;
    url: '/oauth2/{path}';
};
export type HydraOauth2ProxyOauth2PathDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HydraOauth2ProxyOauth2PathDeleteError = HydraOauth2ProxyOauth2PathDeleteErrors[keyof HydraOauth2ProxyOauth2PathDeleteErrors];
export type HydraOauth2ProxyOauth2PathDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HydraOauth2ProxyOauth2PathGetData = {
    body?: never;
    path: {
        /**
         * Path
         */
        path: string;
    };
    query?: never;
    url: '/oauth2/{path}';
};
export type HydraOauth2ProxyOauth2PathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HydraOauth2ProxyOauth2PathGetError = HydraOauth2ProxyOauth2PathGetErrors[keyof HydraOauth2ProxyOauth2PathGetErrors];
export type HydraOauth2ProxyOauth2PathGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HydraOauth2ProxyOauth2PathPatchData = {
    body?: never;
    path: {
        /**
         * Path
         */
        path: string;
    };
    query?: never;
    url: '/oauth2/{path}';
};
export type HydraOauth2ProxyOauth2PathPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HydraOauth2ProxyOauth2PathPatchError = HydraOauth2ProxyOauth2PathPatchErrors[keyof HydraOauth2ProxyOauth2PathPatchErrors];
export type HydraOauth2ProxyOauth2PathPatchResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HydraOauth2ProxyOauth2PathPostData = {
    body?: never;
    path: {
        /**
         * Path
         */
        path: string;
    };
    query?: never;
    url: '/oauth2/{path}';
};
export type HydraOauth2ProxyOauth2PathPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HydraOauth2ProxyOauth2PathPostError = HydraOauth2ProxyOauth2PathPostErrors[keyof HydraOauth2ProxyOauth2PathPostErrors];
export type HydraOauth2ProxyOauth2PathPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HydraOauth2ProxyOauth2PathPutData = {
    body?: never;
    path: {
        /**
         * Path
         */
        path: string;
    };
    query?: never;
    url: '/oauth2/{path}';
};
export type HydraOauth2ProxyOauth2PathPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HydraOauth2ProxyOauth2PathPutError = HydraOauth2ProxyOauth2PathPutErrors[keyof HydraOauth2ProxyOauth2PathPutErrors];
export type HydraOauth2ProxyOauth2PathPutResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type CheckPermissionV1AccessControlCheckPostData = {
    body: CheckRequest;
    path?: never;
    query?: never;
    url: '/v1/access-control/check';
};
export type CheckPermissionV1AccessControlCheckPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CheckPermissionV1AccessControlCheckPostError = CheckPermissionV1AccessControlCheckPostErrors[keyof CheckPermissionV1AccessControlCheckPostErrors];
export type CheckPermissionV1AccessControlCheckPostResponses = {
    /**
     * Successful Response
     */
    200: CheckResponse;
};
export type CheckPermissionV1AccessControlCheckPostResponse = CheckPermissionV1AccessControlCheckPostResponses[keyof CheckPermissionV1AccessControlCheckPostResponses];
export type GetGraphV1AccessControlGraphGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/access-control/graph';
};
export type GetGraphV1AccessControlGraphGetResponses = {
    /**
     * Successful Response
     */
    200: GraphResponse;
};
export type GetGraphV1AccessControlGraphGetResponse = GetGraphV1AccessControlGraphGetResponses[keyof GetGraphV1AccessControlGraphGetResponses];
export type DeleteRelationshipV1AccessControlRelationshipsDeleteData = {
    body: RelationshipWriteRequest;
    path?: never;
    query?: never;
    url: '/v1/access-control/relationships';
};
export type DeleteRelationshipV1AccessControlRelationshipsDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteRelationshipV1AccessControlRelationshipsDeleteError = DeleteRelationshipV1AccessControlRelationshipsDeleteErrors[keyof DeleteRelationshipV1AccessControlRelationshipsDeleteErrors];
export type DeleteRelationshipV1AccessControlRelationshipsDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteRelationshipV1AccessControlRelationshipsDeleteResponse = DeleteRelationshipV1AccessControlRelationshipsDeleteResponses[keyof DeleteRelationshipV1AccessControlRelationshipsDeleteResponses];
export type ListRelationshipsV1AccessControlRelationshipsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Namespace
         */
        namespace?: string | null;
    };
    url: '/v1/access-control/relationships';
};
export type ListRelationshipsV1AccessControlRelationshipsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListRelationshipsV1AccessControlRelationshipsGetError = ListRelationshipsV1AccessControlRelationshipsGetErrors[keyof ListRelationshipsV1AccessControlRelationshipsGetErrors];
export type ListRelationshipsV1AccessControlRelationshipsGetResponses = {
    /**
     * Successful Response
     */
    200: RelationshipsResponse;
};
export type ListRelationshipsV1AccessControlRelationshipsGetResponse = ListRelationshipsV1AccessControlRelationshipsGetResponses[keyof ListRelationshipsV1AccessControlRelationshipsGetResponses];
export type CreateRelationshipV1AccessControlRelationshipsPostData = {
    body: RelationshipWriteRequest;
    path?: never;
    query?: never;
    url: '/v1/access-control/relationships';
};
export type CreateRelationshipV1AccessControlRelationshipsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateRelationshipV1AccessControlRelationshipsPostError = CreateRelationshipV1AccessControlRelationshipsPostErrors[keyof CreateRelationshipV1AccessControlRelationshipsPostErrors];
export type CreateRelationshipV1AccessControlRelationshipsPostResponses = {
    /**
     * Response Create Relationship V1 Access Control Relationships Post
     *
     * Successful Response
     */
    201: {
        [key: string]: unknown;
    };
};
export type CreateRelationshipV1AccessControlRelationshipsPostResponse = CreateRelationshipV1AccessControlRelationshipsPostResponses[keyof CreateRelationshipV1AccessControlRelationshipsPostResponses];
export type ResolveAccessV1AccessControlResolvePostData = {
    body: ResolveRequest;
    path?: never;
    query?: never;
    url: '/v1/access-control/resolve';
};
export type ResolveAccessV1AccessControlResolvePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ResolveAccessV1AccessControlResolvePostError = ResolveAccessV1AccessControlResolvePostErrors[keyof ResolveAccessV1AccessControlResolvePostErrors];
export type ResolveAccessV1AccessControlResolvePostResponses = {
    /**
     * Successful Response
     */
    200: ResolveResponse;
};
export type ResolveAccessV1AccessControlResolvePostResponse = ResolveAccessV1AccessControlResolvePostResponses[keyof ResolveAccessV1AccessControlResolvePostResponses];
export type SyncGrantsV1AccessControlSyncPostData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/access-control/sync';
};
export type SyncGrantsV1AccessControlSyncPostResponses = {
    /**
     * Successful Response
     */
    200: AgentareaApiApiV1AccessControlSyncResponse;
};
export type SyncGrantsV1AccessControlSyncPostResponse = SyncGrantsV1AccessControlSyncPostResponses[keyof SyncGrantsV1AccessControlSyncPostResponses];
export type ListAgentsV1AgentsGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/agents';
};
export type ListAgentsV1AgentsGetResponses = {
    /**
     * Response List Agents V1 Agents Get
     *
     * Successful Response
     */
    200: Array<AgentResponse>;
};
export type ListAgentsV1AgentsGetResponse = ListAgentsV1AgentsGetResponses[keyof ListAgentsV1AgentsGetResponses];
export type ListAgentsV1AgentsGet2Data = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/agents/';
};
export type ListAgentsV1AgentsGet2Responses = {
    /**
     * Response List Agents V1 Agents  Get
     *
     * Successful Response
     */
    200: Array<AgentResponse>;
};
export type ListAgentsV1AgentsGet2Response = ListAgentsV1AgentsGet2Responses[keyof ListAgentsV1AgentsGet2Responses];
export type CreateAgentV1AgentsPostData = {
    body: AgentCreate;
    path?: never;
    query?: never;
    url: '/v1/agents/';
};
export type CreateAgentV1AgentsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateAgentV1AgentsPostError = CreateAgentV1AgentsPostErrors[keyof CreateAgentV1AgentsPostErrors];
export type CreateAgentV1AgentsPostResponses = {
    /**
     * Successful Response
     */
    200: AgentResponse;
};
export type CreateAgentV1AgentsPostResponse = CreateAgentV1AgentsPostResponses[keyof CreateAgentV1AgentsPostResponses];
export type GetAllToolsV1AgentsToolsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Include
         *
         * Comma-separated list of tool types to include (code, mcp)
         */
        include?: string;
        /**
         * Mcp Instance Id
         *
         * Filter MCP tools by specific instance ID
         */
        mcp_instance_id?: string | null;
    };
    url: '/v1/agents/tools';
};
export type GetAllToolsV1AgentsToolsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAllToolsV1AgentsToolsGetError = GetAllToolsV1AgentsToolsGetErrors[keyof GetAllToolsV1AgentsToolsGetErrors];
export type GetAllToolsV1AgentsToolsGetResponses = {
    /**
     * Response Get All Tools V1 Agents Tools Get
     *
     * Successful Response
     */
    200: Array<ToolResponse>;
};
export type GetAllToolsV1AgentsToolsGetResponse = GetAllToolsV1AgentsToolsGetResponses[keyof GetAllToolsV1AgentsToolsGetResponses];
export type DeleteAgentV1AgentsAgentIdDeleteData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}';
};
export type DeleteAgentV1AgentsAgentIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteAgentV1AgentsAgentIdDeleteError = DeleteAgentV1AgentsAgentIdDeleteErrors[keyof DeleteAgentV1AgentsAgentIdDeleteErrors];
export type DeleteAgentV1AgentsAgentIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetAgentV1AgentsAgentIdGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}';
};
export type GetAgentV1AgentsAgentIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAgentV1AgentsAgentIdGetError = GetAgentV1AgentsAgentIdGetErrors[keyof GetAgentV1AgentsAgentIdGetErrors];
export type GetAgentV1AgentsAgentIdGetResponses = {
    /**
     * Successful Response
     */
    200: AgentResponse;
};
export type GetAgentV1AgentsAgentIdGetResponse = GetAgentV1AgentsAgentIdGetResponses[keyof GetAgentV1AgentsAgentIdGetResponses];
export type UpdateAgentV1AgentsAgentIdPatchData = {
    body: AgentUpdate;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}';
};
export type UpdateAgentV1AgentsAgentIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateAgentV1AgentsAgentIdPatchError = UpdateAgentV1AgentsAgentIdPatchErrors[keyof UpdateAgentV1AgentsAgentIdPatchErrors];
export type UpdateAgentV1AgentsAgentIdPatchResponses = {
    /**
     * Successful Response
     */
    200: AgentResponse;
};
export type UpdateAgentV1AgentsAgentIdPatchResponse = UpdateAgentV1AgentsAgentIdPatchResponses[keyof UpdateAgentV1AgentsAgentIdPatchResponses];
export type GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/.well-known/';
};
export type GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetError = GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetErrors[keyof GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetErrors];
export type GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetResponses = {
    /**
     * Response Get Agent Well Known Index V1 Agents  Agent Id   Well Known  Get
     *
     * Successful Response
     */
    200: {
        [key: string]: unknown;
    };
};
export type GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetResponse = GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetResponses[keyof GetAgentWellKnownIndexV1AgentsAgentIdWellKnownGetResponses];
export type GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/.well-known/a2a-info.json';
};
export type GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetError = GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetErrors[keyof GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetErrors];
export type GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetResponses = {
    /**
     * Response Get Agent A2A Info V1 Agents  Agent Id   Well Known A2A Info Json Get
     *
     * Successful Response
     */
    200: {
        [key: string]: unknown;
    };
};
export type GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetResponse = GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetResponses[keyof GetAgentA2aInfoV1AgentsAgentIdWellKnownA2aInfoJsonGetResponses];
export type GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/.well-known/agent-card.json';
};
export type GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetError = GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetErrors[keyof GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetErrors];
export type GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetResponses = {
    /**
     * Successful Response
     */
    200: AgentCard;
};
export type GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetResponse = GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetResponses[keyof GetAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGetResponses];
export type HandleAgentJsonrpcV1AgentsAgentIdA2aRpcPostData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/a2a/rpc';
};
export type HandleAgentJsonrpcV1AgentsAgentIdA2aRpcPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HandleAgentJsonrpcV1AgentsAgentIdA2aRpcPostError = HandleAgentJsonrpcV1AgentsAgentIdA2aRpcPostErrors[keyof HandleAgentJsonrpcV1AgentsAgentIdA2aRpcPostErrors];
export type HandleAgentJsonrpcV1AgentsAgentIdA2aRpcPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/a2a/well-known';
};
export type GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetError = GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetErrors[keyof GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetErrors];
export type GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetResponses = {
    /**
     * Successful Response
     */
    200: AgentCard;
};
export type GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetResponse = GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetResponses[keyof GetAgentWellKnownV1AgentsAgentIdA2aWellKnownGetResponses];
export type InstallAgentV1AgentsAgentIdInstallPostData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/install';
};
export type InstallAgentV1AgentsAgentIdInstallPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type InstallAgentV1AgentsAgentIdInstallPostError = InstallAgentV1AgentsAgentIdInstallPostErrors[keyof InstallAgentV1AgentsAgentIdInstallPostErrors];
export type InstallAgentV1AgentsAgentIdInstallPostResponses = {
    /**
     * Successful Response
     */
    200: AgentResponse;
};
export type InstallAgentV1AgentsAgentIdInstallPostResponse = InstallAgentV1AgentsAgentIdInstallPostResponses[keyof InstallAgentV1AgentsAgentIdInstallPostResponses];
export type GetAgentOverviewV1AgentsAgentIdOverviewGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/overview';
};
export type GetAgentOverviewV1AgentsAgentIdOverviewGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAgentOverviewV1AgentsAgentIdOverviewGetError = GetAgentOverviewV1AgentsAgentIdOverviewGetErrors[keyof GetAgentOverviewV1AgentsAgentIdOverviewGetErrors];
export type GetAgentOverviewV1AgentsAgentIdOverviewGetResponses = {
    /**
     * Successful Response
     */
    200: AgentOverviewResponse;
};
export type GetAgentOverviewV1AgentsAgentIdOverviewGetResponse = GetAgentOverviewV1AgentsAgentIdOverviewGetResponses[keyof GetAgentOverviewV1AgentsAgentIdOverviewGetResponses];
export type ListAgentTasksV1AgentsAgentIdTasksGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: {
        /**
         * Status
         *
         * Filter by task status
         */
        status?: string | null;
        /**
         * Limit
         *
         * Maximum number of tasks to return
         */
        limit?: number;
        /**
         * Offset
         *
         * Number of tasks to skip
         */
        offset?: number;
    };
    url: '/v1/agents/{agent_id}/tasks/';
};
export type ListAgentTasksV1AgentsAgentIdTasksGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListAgentTasksV1AgentsAgentIdTasksGetError = ListAgentTasksV1AgentsAgentIdTasksGetErrors[keyof ListAgentTasksV1AgentsAgentIdTasksGetErrors];
export type ListAgentTasksV1AgentsAgentIdTasksGetResponses = {
    /**
     * Response List Agent Tasks V1 Agents  Agent Id  Tasks  Get
     *
     * Successful Response
     */
    200: Array<TaskResponse>;
};
export type ListAgentTasksV1AgentsAgentIdTasksGetResponse = ListAgentTasksV1AgentsAgentIdTasksGetResponses[keyof ListAgentTasksV1AgentsAgentIdTasksGetResponses];
export type CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostData = {
    body: TaskCreate;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/';
};
export type CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostError = CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostErrors[keyof CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostErrors];
export type CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostData = {
    body: TaskCreate;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/sync';
};
export type CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostError = CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostErrors[keyof CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostErrors];
export type CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostResponses = {
    /**
     * Successful Response
     */
    200: TaskResponse;
};
export type CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostResponse = CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostResponses[keyof CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostResponses];
export type CancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}';
};
export type CancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteError = CancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteErrors[keyof CancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteErrors];
export type CancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetAgentTaskV1AgentsAgentIdTasksTaskIdGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}';
};
export type GetAgentTaskV1AgentsAgentIdTasksTaskIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAgentTaskV1AgentsAgentIdTasksTaskIdGetError = GetAgentTaskV1AgentsAgentIdTasksTaskIdGetErrors[keyof GetAgentTaskV1AgentsAgentIdTasksTaskIdGetErrors];
export type GetAgentTaskV1AgentsAgentIdTasksTaskIdGetResponses = {
    /**
     * Successful Response
     */
    200: TaskResponse;
};
export type GetAgentTaskV1AgentsAgentIdTasksTaskIdGetResponse = GetAgentTaskV1AgentsAgentIdTasksTaskIdGetResponses[keyof GetAgentTaskV1AgentsAgentIdTasksTaskIdGetResponses];
export type SendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostData = {
    body: A2UiActionPayload;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/a2ui/action';
};
export type SendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type SendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostError = SendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostErrors[keyof SendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostErrors];
export type SendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: {
        /**
         * Expires In
         */
        expires_in?: number;
    };
    url: '/v1/agents/{agent_id}/tasks/{task_id}/artifacts';
};
export type ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetError = ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetErrors[keyof ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetErrors];
export type ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetResponses = {
    /**
     * Response List Task Artifacts V1 Agents  Agent Id  Tasks  Task Id  Artifacts Get
     *
     * Successful Response
     */
    200: Array<TaskArtifactItem>;
};
export type ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetResponse = ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetResponses[keyof ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetResponses];
export type DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
        /**
         * Artifact Path
         */
        artifact_path: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/artifacts/files/{artifact_path}';
};
export type DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetError = DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetErrors[keyof DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetErrors];
export type DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostData = {
    body: TaskCommandPayload;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/command';
};
export type SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostError = SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostErrors[keyof SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostErrors];
export type SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: {
        /**
         * Page
         *
         * Page number
         */
        page?: number;
        /**
         * Page Size
         *
         * Number of events per page
         */
        page_size?: number;
        /**
         * Event Type
         *
         * Filter by event type
         */
        event_type?: string | null;
    };
    url: '/v1/agents/{agent_id}/tasks/{task_id}/events';
};
export type GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetError = GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetErrors[keyof GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetErrors];
export type GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetResponses = {
    /**
     * Successful Response
     */
    200: TaskEventResponse;
};
export type GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetResponse = GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetResponses[keyof GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetResponses];
export type StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: {
        /**
         * Include Chunks
         *
         * Include incremental llm.call.chunk token events in the stream
         */
        include_chunks?: boolean;
    };
    url: '/v1/agents/{agent_id}/tasks/{task_id}/events/stream';
};
export type StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetError = StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetErrors[keyof StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetErrors];
export type StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostData = {
    body: TaskInputSubmission;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/input';
};
export type SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostError = SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostErrors[keyof SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostErrors];
export type SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/pause';
};
export type PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostError = PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostErrors[keyof PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostErrors];
export type PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostData = {
    body: EscalationResolution;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/resolve-escalation';
};
export type ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostError = ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostErrors[keyof ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostErrors];
export type ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/resume';
};
export type ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostError = ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostErrors[keyof ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostErrors];
export type ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: {
        /**
         * Prefix
         */
        prefix?: string;
    };
    url: '/v1/agents/{agent_id}/tasks/{task_id}/sandbox/files';
};
export type ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetError = ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetErrors[keyof ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetErrors];
export type ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetResponses = {
    /**
     * Successful Response
     */
    200: SandboxFileListResponse;
};
export type ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetResponse = ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetResponses[keyof ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetResponses];
export type ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
        /**
         * File Path
         */
        file_path: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/sandbox/files/{file_path}';
};
export type ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetError = ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetErrors[keyof ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetErrors];
export type ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/status';
};
export type GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetError = GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetErrors[keyof GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetErrors];
export type GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/tasks/{task_id}/summary';
};
export type GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetError = GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetErrors[keyof GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetErrors];
export type GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetResponses = {
    /**
     * Successful Response
     */
    200: TaskSummary;
};
export type GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetResponse = GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetResponses[keyof GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetResponses];
export type DeleteWalletV1AgentsAgentIdWalletDeleteData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/wallet';
};
export type DeleteWalletV1AgentsAgentIdWalletDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteWalletV1AgentsAgentIdWalletDeleteError = DeleteWalletV1AgentsAgentIdWalletDeleteErrors[keyof DeleteWalletV1AgentsAgentIdWalletDeleteErrors];
export type DeleteWalletV1AgentsAgentIdWalletDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteWalletV1AgentsAgentIdWalletDeleteResponse = DeleteWalletV1AgentsAgentIdWalletDeleteResponses[keyof DeleteWalletV1AgentsAgentIdWalletDeleteResponses];
export type GetWalletV1AgentsAgentIdWalletGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/wallet';
};
export type GetWalletV1AgentsAgentIdWalletGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetWalletV1AgentsAgentIdWalletGetError = GetWalletV1AgentsAgentIdWalletGetErrors[keyof GetWalletV1AgentsAgentIdWalletGetErrors];
export type GetWalletV1AgentsAgentIdWalletGetResponses = {
    /**
     * Successful Response
     */
    200: WalletResponse;
};
export type GetWalletV1AgentsAgentIdWalletGetResponse = GetWalletV1AgentsAgentIdWalletGetResponses[keyof GetWalletV1AgentsAgentIdWalletGetResponses];
export type CreateWalletV1AgentsAgentIdWalletPostData = {
    body: CreateWalletRequest;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/wallet';
};
export type CreateWalletV1AgentsAgentIdWalletPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateWalletV1AgentsAgentIdWalletPostError = CreateWalletV1AgentsAgentIdWalletPostErrors[keyof CreateWalletV1AgentsAgentIdWalletPostErrors];
export type CreateWalletV1AgentsAgentIdWalletPostResponses = {
    /**
     * Successful Response
     */
    201: WalletResponse;
};
export type CreateWalletV1AgentsAgentIdWalletPostResponse = CreateWalletV1AgentsAgentIdWalletPostResponses[keyof CreateWalletV1AgentsAgentIdWalletPostResponses];
export type UpdateWalletV1AgentsAgentIdWalletPutData = {
    body: UpdateWalletRequest;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/wallet';
};
export type UpdateWalletV1AgentsAgentIdWalletPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateWalletV1AgentsAgentIdWalletPutError = UpdateWalletV1AgentsAgentIdWalletPutErrors[keyof UpdateWalletV1AgentsAgentIdWalletPutErrors];
export type UpdateWalletV1AgentsAgentIdWalletPutResponses = {
    /**
     * Successful Response
     */
    200: WalletResponse;
};
export type UpdateWalletV1AgentsAgentIdWalletPutResponse = UpdateWalletV1AgentsAgentIdWalletPutResponses[keyof UpdateWalletV1AgentsAgentIdWalletPutResponses];
export type GetWalletBalanceV1AgentsAgentIdWalletBalanceGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/wallet/balance';
};
export type GetWalletBalanceV1AgentsAgentIdWalletBalanceGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetWalletBalanceV1AgentsAgentIdWalletBalanceGetError = GetWalletBalanceV1AgentsAgentIdWalletBalanceGetErrors[keyof GetWalletBalanceV1AgentsAgentIdWalletBalanceGetErrors];
export type GetWalletBalanceV1AgentsAgentIdWalletBalanceGetResponses = {
    /**
     * Successful Response
     */
    200: WalletBalanceResponse;
};
export type GetWalletBalanceV1AgentsAgentIdWalletBalanceGetResponse = GetWalletBalanceV1AgentsAgentIdWalletBalanceGetResponses[keyof GetWalletBalanceV1AgentsAgentIdWalletBalanceGetResponses];
export type FundWalletV1AgentsAgentIdWalletFundPostData = {
    body: FundWalletRequest;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/agents/{agent_id}/wallet/fund';
};
export type FundWalletV1AgentsAgentIdWalletFundPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type FundWalletV1AgentsAgentIdWalletFundPostError = FundWalletV1AgentsAgentIdWalletFundPostErrors[keyof FundWalletV1AgentsAgentIdWalletFundPostErrors];
export type FundWalletV1AgentsAgentIdWalletFundPostResponses = {
    /**
     * Successful Response
     */
    200: WalletResponse;
};
export type FundWalletV1AgentsAgentIdWalletFundPostResponse = FundWalletV1AgentsAgentIdWalletFundPostResponses[keyof FundWalletV1AgentsAgentIdWalletFundPostResponses];
export type GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetData = {
    body?: never;
    path: {
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: {
        /**
         * Protocol
         *
         * Filter by protocol (x402, mpp)
         */
        protocol?: string | null;
        /**
         * Status
         *
         * Filter by status
         */
        status?: string | null;
        /**
         * From Date
         *
         * Filter from date
         */
        from_date?: string | null;
        /**
         * To Date
         *
         * Filter to date
         */
        to_date?: string | null;
        /**
         * Page
         */
        page?: number;
        /**
         * Page Size
         */
        page_size?: number;
    };
    url: '/v1/agents/{agent_id}/wallet/payments';
};
export type GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetError = GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetErrors[keyof GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetErrors];
export type GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetResponses = {
    /**
     * Successful Response
     */
    200: PaginatedPaymentsResponse;
};
export type GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetResponse = GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetResponses[keyof GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetResponses];
export type ListApiKeysV1ApiKeysGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/api-keys/';
};
export type ListApiKeysV1ApiKeysGetResponses = {
    /**
     * Response List Api Keys V1 Api Keys  Get
     *
     * Successful Response
     */
    200: Array<ApiKeyResponse>;
};
export type ListApiKeysV1ApiKeysGetResponse = ListApiKeysV1ApiKeysGetResponses[keyof ListApiKeysV1ApiKeysGetResponses];
export type CreateApiKeyV1ApiKeysPostData = {
    body: ApiKeyCreateRequest;
    path?: never;
    query?: never;
    url: '/v1/api-keys/';
};
export type CreateApiKeyV1ApiKeysPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateApiKeyV1ApiKeysPostError = CreateApiKeyV1ApiKeysPostErrors[keyof CreateApiKeyV1ApiKeysPostErrors];
export type CreateApiKeyV1ApiKeysPostResponses = {
    /**
     * Successful Response
     */
    201: ApiKeyCreateResponse;
};
export type CreateApiKeyV1ApiKeysPostResponse = CreateApiKeyV1ApiKeysPostResponses[keyof CreateApiKeyV1ApiKeysPostResponses];
export type RevokeApiKeyV1ApiKeysTokenIdDeleteData = {
    body?: never;
    path: {
        /**
         * Token Id
         */
        token_id: string;
    };
    query?: never;
    url: '/v1/api-keys/{token_id}';
};
export type RevokeApiKeyV1ApiKeysTokenIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RevokeApiKeyV1ApiKeysTokenIdDeleteError = RevokeApiKeyV1ApiKeysTokenIdDeleteErrors[keyof RevokeApiKeyV1ApiKeysTokenIdDeleteErrors];
export type RevokeApiKeyV1ApiKeysTokenIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RevokeApiKeyV1ApiKeysTokenIdDeleteResponse = RevokeApiKeyV1ApiKeysTokenIdDeleteResponses[keyof RevokeApiKeyV1ApiKeysTokenIdDeleteResponses];
export type GetApiKeyV1ApiKeysTokenIdGetData = {
    body?: never;
    path: {
        /**
         * Token Id
         */
        token_id: string;
    };
    query?: never;
    url: '/v1/api-keys/{token_id}';
};
export type GetApiKeyV1ApiKeysTokenIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetApiKeyV1ApiKeysTokenIdGetError = GetApiKeyV1ApiKeysTokenIdGetErrors[keyof GetApiKeyV1ApiKeysTokenIdGetErrors];
export type GetApiKeyV1ApiKeysTokenIdGetResponses = {
    /**
     * Successful Response
     */
    200: ApiKeyResponse;
};
export type GetApiKeyV1ApiKeysTokenIdGetResponse = GetApiKeyV1ApiKeysTokenIdGetResponses[keyof GetApiKeyV1ApiKeysTokenIdGetResponses];
export type ListAuditLogsV1AuditLogsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Action
         *
         * Filter by action (e.g. agent.create)
         */
        action?: string | null;
        /**
         * Actor Id
         *
         * Filter by actor ID
         */
        actor_id?: string | null;
        /**
         * Resource Type
         *
         * Filter by resource type
         */
        resource_type?: string | null;
        /**
         * Resource Id
         *
         * Filter by resource ID
         */
        resource_id?: string | null;
        /**
         * Since
         *
         * Events after this time (ISO 8601)
         */
        since?: string | null;
        /**
         * Until
         *
         * Events before this time (ISO 8601)
         */
        until?: string | null;
        /**
         * Cursor
         *
         * Cursor for pagination
         */
        cursor?: string | null;
        /**
         * Limit
         *
         * Max events to return
         */
        limit?: number;
    };
    url: '/v1/audit-logs/';
};
export type ListAuditLogsV1AuditLogsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListAuditLogsV1AuditLogsGetError = ListAuditLogsV1AuditLogsGetErrors[keyof ListAuditLogsV1AuditLogsGetErrors];
export type ListAuditLogsV1AuditLogsGetResponses = {
    /**
     * Successful Response
     */
    200: AuditLogListResponse;
};
export type ListAuditLogsV1AuditLogsGetResponse = ListAuditLogsV1AuditLogsGetResponses[keyof ListAuditLogsV1AuditLogsGetResponses];
export type AnalyzeBundleV1BundlesAnalyzePostData = {
    body: AnalyzeRequest;
    path?: never;
    query?: never;
    url: '/v1/bundles/analyze';
};
export type AnalyzeBundleV1BundlesAnalyzePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AnalyzeBundleV1BundlesAnalyzePostError = AnalyzeBundleV1BundlesAnalyzePostErrors[keyof AnalyzeBundleV1BundlesAnalyzePostErrors];
export type AnalyzeBundleV1BundlesAnalyzePostResponses = {
    /**
     * Successful Response
     */
    200: ImportPreview;
};
export type AnalyzeBundleV1BundlesAnalyzePostResponse = AnalyzeBundleV1BundlesAnalyzePostResponses[keyof AnalyzeBundleV1BundlesAnalyzePostResponses];
export type InstallBundleV1BundlesInstallPostData = {
    body: InstallRequest;
    path?: never;
    query?: never;
    url: '/v1/bundles/install';
};
export type InstallBundleV1BundlesInstallPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type InstallBundleV1BundlesInstallPostError = InstallBundleV1BundlesInstallPostErrors[keyof InstallBundleV1BundlesInstallPostErrors];
export type InstallBundleV1BundlesInstallPostResponses = {
    /**
     * Successful Response
     */
    200: InstallResult;
};
export type InstallBundleV1BundlesInstallPostResponse = InstallBundleV1BundlesInstallPostResponses[keyof InstallBundleV1BundlesInstallPostResponses];
export type ListClientsV1ClientsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Limit
         */
        limit?: number;
        /**
         * Offset
         */
        offset?: number;
    };
    url: '/v1/clients/';
};
export type ListClientsV1ClientsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListClientsV1ClientsGetError = ListClientsV1ClientsGetErrors[keyof ListClientsV1ClientsGetErrors];
export type ListClientsV1ClientsGetResponses = {
    /**
     * Response List Clients V1 Clients  Get
     *
     * Successful Response
     */
    200: Array<ClientResponse>;
};
export type ListClientsV1ClientsGetResponse = ListClientsV1ClientsGetResponses[keyof ListClientsV1ClientsGetResponses];
export type CreateClientV1ClientsPostData = {
    body: ClientCreate;
    path?: never;
    query?: never;
    url: '/v1/clients/';
};
export type CreateClientV1ClientsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateClientV1ClientsPostError = CreateClientV1ClientsPostErrors[keyof CreateClientV1ClientsPostErrors];
export type CreateClientV1ClientsPostResponses = {
    /**
     * Successful Response
     */
    201: ClientResponse;
};
export type CreateClientV1ClientsPostResponse = CreateClientV1ClientsPostResponses[keyof CreateClientV1ClientsPostResponses];
export type DeleteClientV1ClientsClientIdDeleteData = {
    body?: never;
    path: {
        /**
         * Client Id
         */
        client_id: string;
    };
    query?: never;
    url: '/v1/clients/{client_id}';
};
export type DeleteClientV1ClientsClientIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteClientV1ClientsClientIdDeleteError = DeleteClientV1ClientsClientIdDeleteErrors[keyof DeleteClientV1ClientsClientIdDeleteErrors];
export type DeleteClientV1ClientsClientIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteClientV1ClientsClientIdDeleteResponse = DeleteClientV1ClientsClientIdDeleteResponses[keyof DeleteClientV1ClientsClientIdDeleteResponses];
export type GetClientV1ClientsClientIdGetData = {
    body?: never;
    path: {
        /**
         * Client Id
         */
        client_id: string;
    };
    query?: never;
    url: '/v1/clients/{client_id}';
};
export type GetClientV1ClientsClientIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetClientV1ClientsClientIdGetError = GetClientV1ClientsClientIdGetErrors[keyof GetClientV1ClientsClientIdGetErrors];
export type GetClientV1ClientsClientIdGetResponses = {
    /**
     * Successful Response
     */
    200: ClientResponse;
};
export type GetClientV1ClientsClientIdGetResponse = GetClientV1ClientsClientIdGetResponses[keyof GetClientV1ClientsClientIdGetResponses];
export type UpdateClientV1ClientsClientIdPatchData = {
    body: ClientUpdate;
    path: {
        /**
         * Client Id
         */
        client_id: string;
    };
    query?: never;
    url: '/v1/clients/{client_id}';
};
export type UpdateClientV1ClientsClientIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateClientV1ClientsClientIdPatchError = UpdateClientV1ClientsClientIdPatchErrors[keyof UpdateClientV1ClientsClientIdPatchErrors];
export type UpdateClientV1ClientsClientIdPatchResponses = {
    /**
     * Successful Response
     */
    200: ClientResponse;
};
export type UpdateClientV1ClientsClientIdPatchResponse = UpdateClientV1ClientsClientIdPatchResponses[keyof UpdateClientV1ClientsClientIdPatchResponses];
export type AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostData = {
    body: McpInstanceAssociationBody;
    path: {
        /**
         * Client Id
         */
        client_id: string;
    };
    query?: never;
    url: '/v1/clients/{client_id}/mcp-instances';
};
export type AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostError = AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostErrors[keyof AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostErrors];
export type AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostResponse = AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostResponses[keyof AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostResponses];
export type RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteData = {
    body?: never;
    path: {
        /**
         * Client Id
         */
        client_id: string;
        /**
         * Mcp Instance Id
         */
        mcp_instance_id: string;
    };
    query?: never;
    url: '/v1/clients/{client_id}/mcp-instances/{mcp_instance_id}';
};
export type RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteError = RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteErrors[keyof RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteErrors];
export type RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteResponse = RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteResponses[keyof RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteResponses];
export type PullFromProjectV1ClientsClientIdPullFromProjectPostData = {
    body: SourceProjectBody;
    path: {
        /**
         * Client Id
         */
        client_id: string;
    };
    query?: never;
    url: '/v1/clients/{client_id}/pull-from-project';
};
export type PullFromProjectV1ClientsClientIdPullFromProjectPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type PullFromProjectV1ClientsClientIdPullFromProjectPostError = PullFromProjectV1ClientsClientIdPullFromProjectPostErrors[keyof PullFromProjectV1ClientsClientIdPullFromProjectPostErrors];
export type PullFromProjectV1ClientsClientIdPullFromProjectPostResponses = {
    /**
     * Successful Response
     */
    200: ClientResponse;
};
export type PullFromProjectV1ClientsClientIdPullFromProjectPostResponse = PullFromProjectV1ClientsClientIdPullFromProjectPostResponses[keyof PullFromProjectV1ClientsClientIdPullFromProjectPostResponses];
export type AddSkillToClientV1ClientsClientIdSkillsPostData = {
    body: AssociationBody;
    path: {
        /**
         * Client Id
         */
        client_id: string;
    };
    query?: never;
    url: '/v1/clients/{client_id}/skills';
};
export type AddSkillToClientV1ClientsClientIdSkillsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AddSkillToClientV1ClientsClientIdSkillsPostError = AddSkillToClientV1ClientsClientIdSkillsPostErrors[keyof AddSkillToClientV1ClientsClientIdSkillsPostErrors];
export type AddSkillToClientV1ClientsClientIdSkillsPostResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type AddSkillToClientV1ClientsClientIdSkillsPostResponse = AddSkillToClientV1ClientsClientIdSkillsPostResponses[keyof AddSkillToClientV1ClientsClientIdSkillsPostResponses];
export type RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteData = {
    body?: never;
    path: {
        /**
         * Client Id
         */
        client_id: string;
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/clients/{client_id}/skills/{skill_id}';
};
export type RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteError = RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteErrors[keyof RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteErrors];
export type RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteResponse = RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteResponses[keyof RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteResponses];
export type ListWorkspaceFilesV1FilesGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/files';
};
export type ListWorkspaceFilesV1FilesGetResponses = {
    /**
     * Successful Response
     */
    200: WorkspaceFileListResponse;
};
export type ListWorkspaceFilesV1FilesGetResponse = ListWorkspaceFilesV1FilesGetResponses[keyof ListWorkspaceFilesV1FilesGetResponses];
export type UploadFileV1FilesPostData = {
    body: BodyUploadFileV1FilesPost;
    path?: never;
    query?: never;
    url: '/v1/files';
};
export type UploadFileV1FilesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UploadFileV1FilesPostError = UploadFileV1FilesPostErrors[keyof UploadFileV1FilesPostErrors];
export type UploadFileV1FilesPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type StreamWorkspaceFileV1FilesDownloadFilePathGetData = {
    body?: never;
    path: {
        /**
         * File Path
         */
        file_path: string;
    };
    query?: never;
    url: '/v1/files/download/{file_path}';
};
export type StreamWorkspaceFileV1FilesDownloadFilePathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type StreamWorkspaceFileV1FilesDownloadFilePathGetError = StreamWorkspaceFileV1FilesDownloadFilePathGetErrors[keyof StreamWorkspaceFileV1FilesDownloadFilePathGetErrors];
export type StreamWorkspaceFileV1FilesDownloadFilePathGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type WorkspaceFileHistoryV1FilesHistoryGetData = {
    body?: never;
    path?: never;
    query: {
        /**
         * Path
         */
        path: string;
    };
    url: '/v1/files/history';
};
export type WorkspaceFileHistoryV1FilesHistoryGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type WorkspaceFileHistoryV1FilesHistoryGetError = WorkspaceFileHistoryV1FilesHistoryGetErrors[keyof WorkspaceFileHistoryV1FilesHistoryGetErrors];
export type WorkspaceFileHistoryV1FilesHistoryGetResponses = {
    /**
     * Successful Response
     */
    200: ArtifactHistoryResponse;
};
export type WorkspaceFileHistoryV1FilesHistoryGetResponse = WorkspaceFileHistoryV1FilesHistoryGetResponses[keyof WorkspaceFileHistoryV1FilesHistoryGetResponses];
export type CreateAttachmentUploadUrlV1FilesUploadUrlPostData = {
    body: PresignUploadRequest;
    path?: never;
    query?: never;
    url: '/v1/files/upload-url';
};
export type CreateAttachmentUploadUrlV1FilesUploadUrlPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateAttachmentUploadUrlV1FilesUploadUrlPostError = CreateAttachmentUploadUrlV1FilesUploadUrlPostErrors[keyof CreateAttachmentUploadUrlV1FilesUploadUrlPostErrors];
export type CreateAttachmentUploadUrlV1FilesUploadUrlPostResponses = {
    /**
     * Successful Response
     */
    200: PresignUploadResponse;
};
export type CreateAttachmentUploadUrlV1FilesUploadUrlPostResponse = CreateAttachmentUploadUrlV1FilesUploadUrlPostResponses[keyof CreateAttachmentUploadUrlV1FilesUploadUrlPostResponses];
export type DownloadWorkspaceFileV1FilesFilePathGetData = {
    body?: never;
    path: {
        /**
         * File Path
         */
        file_path: string;
    };
    query?: never;
    url: '/v1/files/{file_path}';
};
export type DownloadWorkspaceFileV1FilesFilePathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DownloadWorkspaceFileV1FilesFilePathGetError = DownloadWorkspaceFileV1FilesFilePathGetErrors[keyof DownloadWorkspaceFileV1FilesFilePathGetErrors];
export type DownloadWorkspaceFileV1FilesFilePathGetResponses = {
    /**
     * Successful Response
     */
    200: WorkspaceFileDownloadResponse;
};
export type DownloadWorkspaceFileV1FilesFilePathGetResponse = DownloadWorkspaceFileV1FilesFilePathGetResponses[keyof DownloadWorkspaceFileV1FilesFilePathGetResponses];
export type PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostData = {
    body: EffectivePolicyPreviewRequest;
    path?: never;
    query?: never;
    url: '/v1/governance/effective-policy/preview';
};
export type PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostError = PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostErrors[keyof PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostErrors];
export type PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponses = {
    /**
     * Successful Response
     */
    200: EffectivePolicyResponse;
};
export type PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponse = PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponses[keyof PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponses];
export type GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetData = {
    body?: never;
    path: {
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/governance/task-policy-snapshots/{task_id}';
};
export type GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetError = GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetErrors[keyof GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetErrors];
export type GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetResponses = {
    /**
     * Successful Response
     */
    200: EffectivePolicyResponse;
};
export type GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetResponse = GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetResponses[keyof GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetResponses];
export type GetInboxItemsV1InboxGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Status
         *
         * Filter to a specific inbox status
         */
        status?: string | null;
        /**
         * Agent Id
         *
         * Filter by agent ID
         */
        agent_id?: string | null;
        /**
         * Page
         */
        page?: number;
        /**
         * Page Size
         */
        page_size?: number;
    };
    url: '/v1/inbox/';
};
export type GetInboxItemsV1InboxGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetInboxItemsV1InboxGetError = GetInboxItemsV1InboxGetErrors[keyof GetInboxItemsV1InboxGetErrors];
export type GetInboxItemsV1InboxGetResponses = {
    /**
     * Successful Response
     */
    200: InboxResponse;
};
export type GetInboxItemsV1InboxGetResponse = GetInboxItemsV1InboxGetResponses[keyof GetInboxItemsV1InboxGetResponses];
export type AcceptInvitationV1InvitationsAcceptPostData = {
    body: AcceptInvitationBody;
    path?: never;
    query?: never;
    url: '/v1/invitations/accept';
};
export type AcceptInvitationV1InvitationsAcceptPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AcceptInvitationV1InvitationsAcceptPostError = AcceptInvitationV1InvitationsAcceptPostErrors[keyof AcceptInvitationV1InvitationsAcceptPostErrors];
export type AcceptInvitationV1InvitationsAcceptPostResponses = {
    /**
     * Successful Response
     */
    200: AcceptInvitationResponse;
};
export type AcceptInvitationV1InvitationsAcceptPostResponse = AcceptInvitationV1InvitationsAcceptPostResponses[keyof AcceptInvitationV1InvitationsAcceptPostResponses];
export type ListMcpAuthConfigsV1McpAuthConfigsGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/mcp-auth-configs/';
};
export type ListMcpAuthConfigsV1McpAuthConfigsGetResponses = {
    /**
     * Response List Mcp Auth Configs V1 Mcp Auth Configs  Get
     *
     * Successful Response
     */
    200: Array<McpAuthConfigResponse>;
};
export type ListMcpAuthConfigsV1McpAuthConfigsGetResponse = ListMcpAuthConfigsV1McpAuthConfigsGetResponses[keyof ListMcpAuthConfigsV1McpAuthConfigsGetResponses];
export type CreateMcpAuthConfigV1McpAuthConfigsPostData = {
    body: McpAuthConfigCreateRequest;
    path?: never;
    query?: never;
    url: '/v1/mcp-auth-configs/';
};
export type CreateMcpAuthConfigV1McpAuthConfigsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateMcpAuthConfigV1McpAuthConfigsPostError = CreateMcpAuthConfigV1McpAuthConfigsPostErrors[keyof CreateMcpAuthConfigV1McpAuthConfigsPostErrors];
export type CreateMcpAuthConfigV1McpAuthConfigsPostResponses = {
    /**
     * Successful Response
     */
    201: McpAuthConfigResponse;
};
export type CreateMcpAuthConfigV1McpAuthConfigsPostResponse = CreateMcpAuthConfigV1McpAuthConfigsPostResponses[keyof CreateMcpAuthConfigV1McpAuthConfigsPostResponses];
export type DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteData = {
    body?: never;
    path: {
        /**
         * Config Id
         */
        config_id: string;
    };
    query?: never;
    url: '/v1/mcp-auth-configs/{config_id}';
};
export type DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteError = DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteErrors[keyof DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteErrors];
export type DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteResponse = DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteResponses[keyof DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteResponses];
export type GetMcpAuthConfigV1McpAuthConfigsConfigIdGetData = {
    body?: never;
    path: {
        /**
         * Config Id
         */
        config_id: string;
    };
    query?: never;
    url: '/v1/mcp-auth-configs/{config_id}';
};
export type GetMcpAuthConfigV1McpAuthConfigsConfigIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetMcpAuthConfigV1McpAuthConfigsConfigIdGetError = GetMcpAuthConfigV1McpAuthConfigsConfigIdGetErrors[keyof GetMcpAuthConfigV1McpAuthConfigsConfigIdGetErrors];
export type GetMcpAuthConfigV1McpAuthConfigsConfigIdGetResponses = {
    /**
     * Successful Response
     */
    200: McpAuthConfigResponse;
};
export type GetMcpAuthConfigV1McpAuthConfigsConfigIdGetResponse = GetMcpAuthConfigV1McpAuthConfigsConfigIdGetResponses[keyof GetMcpAuthConfigV1McpAuthConfigsConfigIdGetResponses];
export type UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutData = {
    body: McpAuthConfigUpdateRequest;
    path: {
        /**
         * Config Id
         */
        config_id: string;
    };
    query?: never;
    url: '/v1/mcp-auth-configs/{config_id}';
};
export type UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutError = UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutErrors[keyof UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutErrors];
export type UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutResponses = {
    /**
     * Successful Response
     */
    200: McpAuthConfigResponse;
};
export type UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutResponse = UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutResponses[keyof UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutResponses];
export type CreateOauthLinkV1McpOauthLinksPostData = {
    body: OAuthLinkCreateRequest;
    path?: never;
    query?: never;
    url: '/v1/mcp-oauth-links/';
};
export type CreateOauthLinkV1McpOauthLinksPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateOauthLinkV1McpOauthLinksPostError = CreateOauthLinkV1McpOauthLinksPostErrors[keyof CreateOauthLinkV1McpOauthLinksPostErrors];
export type CreateOauthLinkV1McpOauthLinksPostResponses = {
    /**
     * Successful Response
     */
    201: OAuthLinkResponse;
};
export type CreateOauthLinkV1McpOauthLinksPostResponse = CreateOauthLinkV1McpOauthLinksPostResponses[keyof CreateOauthLinkV1McpOauthLinksPostResponses];
export type ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-oauth-links/instance/{instance_id}';
};
export type ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetError = ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetErrors[keyof ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetErrors];
export type ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetResponses = {
    /**
     * Response List Oauth Links For Instance V1 Mcp Oauth Links Instance  Instance Id  Get
     *
     * Successful Response
     */
    200: Array<OAuthLinkResponse>;
};
export type ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetResponse = ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetResponses[keyof ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetResponses];
export type RevokeOauthLinkV1McpOauthLinksLinkIdDeleteData = {
    body?: never;
    path: {
        /**
         * Link Id
         */
        link_id: string;
    };
    query?: never;
    url: '/v1/mcp-oauth-links/{link_id}';
};
export type RevokeOauthLinkV1McpOauthLinksLinkIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RevokeOauthLinkV1McpOauthLinksLinkIdDeleteError = RevokeOauthLinkV1McpOauthLinksLinkIdDeleteErrors[keyof RevokeOauthLinkV1McpOauthLinksLinkIdDeleteErrors];
export type RevokeOauthLinkV1McpOauthLinksLinkIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RevokeOauthLinkV1McpOauthLinksLinkIdDeleteResponse = RevokeOauthLinkV1McpOauthLinksLinkIdDeleteResponses[keyof RevokeOauthLinkV1McpOauthLinksLinkIdDeleteResponses];
export type GetOauthLinkV1McpOauthLinksLinkIdGetData = {
    body?: never;
    path: {
        /**
         * Link Id
         */
        link_id: string;
    };
    query?: never;
    url: '/v1/mcp-oauth-links/{link_id}';
};
export type GetOauthLinkV1McpOauthLinksLinkIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetOauthLinkV1McpOauthLinksLinkIdGetError = GetOauthLinkV1McpOauthLinksLinkIdGetErrors[keyof GetOauthLinkV1McpOauthLinksLinkIdGetErrors];
export type GetOauthLinkV1McpOauthLinksLinkIdGetResponses = {
    /**
     * Successful Response
     */
    200: OAuthLinkResponse;
};
export type GetOauthLinkV1McpOauthLinksLinkIdGetResponse = GetOauthLinkV1McpOauthLinksLinkIdGetResponses[keyof GetOauthLinkV1McpOauthLinksLinkIdGetResponses];
export type OauthAuthorizeV1McpOauthAuthorizeGetData = {
    body?: never;
    path?: never;
    query: {
        /**
         * Instance Id
         *
         * MCP instance to connect
         */
        instance_id: string;
        /**
         * Return To
         *
         * Frontend URL to redirect after OAuth completes
         */
        return_to?: string;
    };
    url: '/v1/mcp-oauth/authorize';
};
export type OauthAuthorizeV1McpOauthAuthorizeGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type OauthAuthorizeV1McpOauthAuthorizeGetError = OauthAuthorizeV1McpOauthAuthorizeGetErrors[keyof OauthAuthorizeV1McpOauthAuthorizeGetErrors];
export type OauthAuthorizeV1McpOauthAuthorizeGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type OauthCallbackV1McpOauthCallbackGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Code
         */
        code?: string;
        /**
         * State
         */
        state?: string;
        /**
         * Error
         */
        error?: string;
        /**
         * Error Description
         */
        error_description?: string;
    };
    url: '/v1/mcp-oauth/callback';
};
export type OauthCallbackV1McpOauthCallbackGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type OauthCallbackV1McpOauthCallbackGetError = OauthCallbackV1McpOauthCallbackGetErrors[keyof OauthCallbackV1McpOauthCallbackGetErrors];
export type OauthCallbackV1McpOauthCallbackGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ListMcpServerInstancesV1McpServerInstancesGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/mcp-server-instances/';
};
export type ListMcpServerInstancesV1McpServerInstancesGetResponses = {
    /**
     * Response List Mcp Server Instances V1 Mcp Server Instances  Get
     *
     * Successful Response
     */
    200: Array<McpServerInstanceResponse>;
};
export type ListMcpServerInstancesV1McpServerInstancesGetResponse = ListMcpServerInstancesV1McpServerInstancesGetResponses[keyof ListMcpServerInstancesV1McpServerInstancesGetResponses];
export type CreateMcpServerInstanceV1McpServerInstancesPostData = {
    body: McpServerInstanceCreate;
    path?: never;
    query?: never;
    url: '/v1/mcp-server-instances/';
};
export type CreateMcpServerInstanceV1McpServerInstancesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateMcpServerInstanceV1McpServerInstancesPostError = CreateMcpServerInstanceV1McpServerInstancesPostErrors[keyof CreateMcpServerInstanceV1McpServerInstancesPostErrors];
export type CreateMcpServerInstanceV1McpServerInstancesPostResponses = {
    /**
     * Successful Response
     */
    201: McpServerInstanceResponse;
};
export type CreateMcpServerInstanceV1McpServerInstancesPostResponse = CreateMcpServerInstanceV1McpServerInstancesPostResponses[keyof CreateMcpServerInstanceV1McpServerInstancesPostResponses];
export type CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostData = {
    /**
     * Data
     */
    body: {
        [key: string]: unknown;
    };
    path?: never;
    query?: never;
    url: '/v1/mcp-server-instances/check';
};
export type CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostError = CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostErrors[keyof CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostErrors];
export type CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetContainersHealthV1McpServerInstancesHealthContainersGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/mcp-server-instances/health/containers';
};
export type GetContainersHealthV1McpServerInstancesHealthContainersGetResponses = {
    /**
     * Successful Response
     */
    200: McpContainersHealthResponse;
};
export type GetContainersHealthV1McpServerInstancesHealthContainersGetResponse = GetContainersHealthV1McpServerInstancesHealthContainersGetResponses[keyof GetContainersHealthV1McpServerInstancesHealthContainersGetResponses];
export type ValidateInstanceSpecV1McpServerInstancesValidatePostData = {
    body: ValidateRequest;
    path?: never;
    query?: never;
    url: '/v1/mcp-server-instances/validate';
};
export type ValidateInstanceSpecV1McpServerInstancesValidatePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ValidateInstanceSpecV1McpServerInstancesValidatePostError = ValidateInstanceSpecV1McpServerInstancesValidatePostErrors[keyof ValidateInstanceSpecV1McpServerInstancesValidatePostErrors];
export type ValidateInstanceSpecV1McpServerInstancesValidatePostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ValidateConnectionV1McpServerInstancesValidateConnectionPostData = {
    /**
     * Data
     */
    body: {
        [key: string]: unknown;
    };
    path?: never;
    query?: never;
    url: '/v1/mcp-server-instances/validate-connection';
};
export type ValidateConnectionV1McpServerInstancesValidateConnectionPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ValidateConnectionV1McpServerInstancesValidateConnectionPostError = ValidateConnectionV1McpServerInstancesValidateConnectionPostErrors[keyof ValidateConnectionV1McpServerInstancesValidateConnectionPostErrors];
export type ValidateConnectionV1McpServerInstancesValidateConnectionPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type CreateMcpServerConnectionV1McpServerInstancesWithSpecPostData = {
    body: McpServerConnectionCreateRequest;
    path?: never;
    query?: never;
    url: '/v1/mcp-server-instances/with-spec';
};
export type CreateMcpServerConnectionV1McpServerInstancesWithSpecPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateMcpServerConnectionV1McpServerInstancesWithSpecPostError = CreateMcpServerConnectionV1McpServerInstancesWithSpecPostErrors[keyof CreateMcpServerConnectionV1McpServerInstancesWithSpecPostErrors];
export type CreateMcpServerConnectionV1McpServerInstancesWithSpecPostResponses = {
    /**
     * Successful Response
     */
    201: McpServerInstanceResponse;
};
export type CreateMcpServerConnectionV1McpServerInstancesWithSpecPostResponse = CreateMcpServerConnectionV1McpServerInstancesWithSpecPostResponses[keyof CreateMcpServerConnectionV1McpServerInstancesWithSpecPostResponses];
export type DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}';
};
export type DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteError = DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteErrors[keyof DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteErrors];
export type DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetMcpServerInstanceV1McpServerInstancesInstanceIdGetData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}';
};
export type GetMcpServerInstanceV1McpServerInstancesInstanceIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetMcpServerInstanceV1McpServerInstancesInstanceIdGetError = GetMcpServerInstanceV1McpServerInstancesInstanceIdGetErrors[keyof GetMcpServerInstanceV1McpServerInstancesInstanceIdGetErrors];
export type GetMcpServerInstanceV1McpServerInstancesInstanceIdGetResponses = {
    /**
     * Successful Response
     */
    200: McpServerInstanceResponse;
};
export type GetMcpServerInstanceV1McpServerInstancesInstanceIdGetResponse = GetMcpServerInstanceV1McpServerInstancesInstanceIdGetResponses[keyof GetMcpServerInstanceV1McpServerInstancesInstanceIdGetResponses];
export type UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchData = {
    body: McpServerInstanceUpdate;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}';
};
export type UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchError = UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchErrors[keyof UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchErrors];
export type UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchResponses = {
    /**
     * Successful Response
     */
    200: McpServerInstanceResponse;
};
export type UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchResponse = UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchResponses[keyof UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchResponses];
export type ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}/consumers';
};
export type ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetError = ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetErrors[keyof ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetErrors];
export type ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetResponses = {
    /**
     * Response List Mcp Server Instance Consumers V1 Mcp Server Instances  Instance Id  Consumers Get
     *
     * Successful Response
     */
    200: Array<McpInstanceConsumer>;
};
export type ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetResponse = ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetResponses[keyof ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetResponses];
export type DiscoverMcpServerInstanceToolsV1McpServerInstancesInstanceIdDiscoverToolsPostData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}/discover-tools';
};
export type DiscoverMcpServerInstanceToolsV1McpServerInstancesInstanceIdDiscoverToolsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DiscoverMcpServerInstanceToolsV1McpServerInstancesInstanceIdDiscoverToolsPostError = DiscoverMcpServerInstanceToolsV1McpServerInstancesInstanceIdDiscoverToolsPostErrors[keyof DiscoverMcpServerInstanceToolsV1McpServerInstancesInstanceIdDiscoverToolsPostErrors];
export type DiscoverMcpServerInstanceToolsV1McpServerInstancesInstanceIdDiscoverToolsPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}/environment';
};
export type GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetError = GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetErrors[keyof GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetErrors];
export type GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostData = {
    /**
     * Data
     */
    body: {
        [key: string]: unknown;
    };
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}/oauth-link';
};
export type CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostError = CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostErrors[keyof CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostErrors];
export type CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}/oauth-links';
};
export type ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetError = ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetErrors[keyof ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetErrors];
export type ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ProbeInstanceAuthV1McpServerInstancesInstanceIdProbePostData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}/probe';
};
export type ProbeInstanceAuthV1McpServerInstancesInstanceIdProbePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ProbeInstanceAuthV1McpServerInstancesInstanceIdProbePostError = ProbeInstanceAuthV1McpServerInstancesInstanceIdProbePostErrors[keyof ProbeInstanceAuthV1McpServerInstancesInstanceIdProbePostErrors];
export type ProbeInstanceAuthV1McpServerInstancesInstanceIdProbePostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type RunTestAuthV1McpServerInstancesInstanceIdTestAuthPostData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}/test-auth';
};
export type RunTestAuthV1McpServerInstancesInstanceIdTestAuthPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RunTestAuthV1McpServerInstancesInstanceIdTestAuthPostError = RunTestAuthV1McpServerInstancesInstanceIdTestAuthPostErrors[keyof RunTestAuthV1McpServerInstancesInstanceIdTestAuthPostErrors];
export type RunTestAuthV1McpServerInstancesInstanceIdTestAuthPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type VerifyMcpServerInstanceV1McpServerInstancesInstanceIdVerifyPostData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp-server-instances/{instance_id}/verify';
};
export type VerifyMcpServerInstanceV1McpServerInstancesInstanceIdVerifyPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type VerifyMcpServerInstanceV1McpServerInstancesInstanceIdVerifyPostError = VerifyMcpServerInstanceV1McpServerInstancesInstanceIdVerifyPostErrors[keyof VerifyMcpServerInstanceV1McpServerInstancesInstanceIdVerifyPostErrors];
export type VerifyMcpServerInstanceV1McpServerInstancesInstanceIdVerifyPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ListMcpServersV1McpServersGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Status
         */
        status?: string | null;
        /**
         * Is Public
         */
        is_public?: boolean | null;
        /**
         * Tag
         */
        tag?: string | null;
        /**
         * Page
         */
        page?: number;
        /**
         * Page Size
         */
        page_size?: number;
        /**
         * Search
         */
        search?: string | null;
    };
    url: '/v1/mcp-servers/';
};
export type ListMcpServersV1McpServersGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListMcpServersV1McpServersGetError = ListMcpServersV1McpServersGetErrors[keyof ListMcpServersV1McpServersGetErrors];
export type ListMcpServersV1McpServersGetResponses = {
    /**
     * Successful Response
     */
    200: PaginatedResponseMcpServerResponse;
};
export type ListMcpServersV1McpServersGetResponse = ListMcpServersV1McpServersGetResponses[keyof ListMcpServersV1McpServersGetResponses];
export type CreateMcpServerV1McpServersPostData = {
    body: McpServerCreate;
    path?: never;
    query?: never;
    url: '/v1/mcp-servers/';
};
export type CreateMcpServerV1McpServersPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateMcpServerV1McpServersPostError = CreateMcpServerV1McpServersPostErrors[keyof CreateMcpServerV1McpServersPostErrors];
export type CreateMcpServerV1McpServersPostResponses = {
    /**
     * Successful Response
     */
    200: McpServerResponse;
};
export type CreateMcpServerV1McpServersPostResponse = CreateMcpServerV1McpServersPostResponses[keyof CreateMcpServerV1McpServersPostResponses];
export type DeleteMcpServerV1McpServersServerIdDeleteData = {
    body?: never;
    path: {
        /**
         * Server Id
         */
        server_id: string;
    };
    query?: never;
    url: '/v1/mcp-servers/{server_id}';
};
export type DeleteMcpServerV1McpServersServerIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteMcpServerV1McpServersServerIdDeleteError = DeleteMcpServerV1McpServersServerIdDeleteErrors[keyof DeleteMcpServerV1McpServersServerIdDeleteErrors];
export type DeleteMcpServerV1McpServersServerIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetMcpServerV1McpServersServerIdGetData = {
    body?: never;
    path: {
        /**
         * Server Id
         */
        server_id: string;
    };
    query?: never;
    url: '/v1/mcp-servers/{server_id}';
};
export type GetMcpServerV1McpServersServerIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetMcpServerV1McpServersServerIdGetError = GetMcpServerV1McpServersServerIdGetErrors[keyof GetMcpServerV1McpServersServerIdGetErrors];
export type GetMcpServerV1McpServersServerIdGetResponses = {
    /**
     * Successful Response
     */
    200: McpServerResponse;
};
export type GetMcpServerV1McpServersServerIdGetResponse = GetMcpServerV1McpServersServerIdGetResponses[keyof GetMcpServerV1McpServersServerIdGetResponses];
export type UpdateMcpServerV1McpServersServerIdPatchData = {
    body: McpServerUpdate;
    path: {
        /**
         * Server Id
         */
        server_id: string;
    };
    query?: never;
    url: '/v1/mcp-servers/{server_id}';
};
export type UpdateMcpServerV1McpServersServerIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateMcpServerV1McpServersServerIdPatchError = UpdateMcpServerV1McpServersServerIdPatchErrors[keyof UpdateMcpServerV1McpServersServerIdPatchErrors];
export type UpdateMcpServerV1McpServersServerIdPatchResponses = {
    /**
     * Successful Response
     */
    200: McpServerResponse;
};
export type UpdateMcpServerV1McpServersServerIdPatchResponse = UpdateMcpServerV1McpServersServerIdPatchResponses[keyof UpdateMcpServerV1McpServersServerIdPatchResponses];
export type DeployMcpServerV1McpServersServerIdDeployPostData = {
    body?: never;
    path: {
        /**
         * Server Id
         */
        server_id: string;
    };
    query?: never;
    url: '/v1/mcp-servers/{server_id}/deploy';
};
export type DeployMcpServerV1McpServersServerIdDeployPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeployMcpServerV1McpServersServerIdDeployPostError = DeployMcpServerV1McpServersServerIdDeployPostErrors[keyof DeployMcpServerV1McpServersServerIdDeployPostErrors];
export type DeployMcpServerV1McpServersServerIdDeployPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ProxyInstanceV1McpInstanceIdMcpDeleteData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp/{instance_id}/mcp';
};
export type ProxyInstanceV1McpInstanceIdMcpDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ProxyInstanceV1McpInstanceIdMcpDeleteError = ProxyInstanceV1McpInstanceIdMcpDeleteErrors[keyof ProxyInstanceV1McpInstanceIdMcpDeleteErrors];
export type ProxyInstanceV1McpInstanceIdMcpDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ProxyInstanceV1McpInstanceIdMcpGetData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp/{instance_id}/mcp';
};
export type ProxyInstanceV1McpInstanceIdMcpGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ProxyInstanceV1McpInstanceIdMcpGetError = ProxyInstanceV1McpInstanceIdMcpGetErrors[keyof ProxyInstanceV1McpInstanceIdMcpGetErrors];
export type ProxyInstanceV1McpInstanceIdMcpGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ProxyInstanceV1McpInstanceIdMcpPostData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/mcp/{instance_id}/mcp';
};
export type ProxyInstanceV1McpInstanceIdMcpPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ProxyInstanceV1McpInstanceIdMcpPostError = ProxyInstanceV1McpInstanceIdMcpPostErrors[keyof ProxyInstanceV1McpInstanceIdMcpPostErrors];
export type ProxyInstanceV1McpInstanceIdMcpPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ListModelInstancesV1ModelInstancesGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Provider Config Id
         */
        provider_config_id?: string | null;
        /**
         * Model Spec Id
         */
        model_spec_id?: string | null;
        /**
         * Is Active
         */
        is_active?: boolean | null;
    };
    url: '/v1/model-instances/';
};
export type ListModelInstancesV1ModelInstancesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListModelInstancesV1ModelInstancesGetError = ListModelInstancesV1ModelInstancesGetErrors[keyof ListModelInstancesV1ModelInstancesGetErrors];
export type ListModelInstancesV1ModelInstancesGetResponses = {
    /**
     * Response List Model Instances V1 Model Instances  Get
     *
     * Successful Response
     */
    200: Array<ModelInstanceResponse>;
};
export type ListModelInstancesV1ModelInstancesGetResponse = ListModelInstancesV1ModelInstancesGetResponses[keyof ListModelInstancesV1ModelInstancesGetResponses];
export type CreateModelInstanceV1ModelInstancesPostData = {
    body: ModelInstanceCreate;
    path?: never;
    query?: never;
    url: '/v1/model-instances/';
};
export type CreateModelInstanceV1ModelInstancesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateModelInstanceV1ModelInstancesPostError = CreateModelInstanceV1ModelInstancesPostErrors[keyof CreateModelInstanceV1ModelInstancesPostErrors];
export type CreateModelInstanceV1ModelInstancesPostResponses = {
    /**
     * Successful Response
     */
    200: ModelInstanceResponse;
};
export type CreateModelInstanceV1ModelInstancesPostResponse = CreateModelInstanceV1ModelInstancesPostResponses[keyof CreateModelInstanceV1ModelInstancesPostResponses];
export type CreateModelInstancesBulkV1ModelInstancesBulkPostData = {
    body: ModelInstanceBulkCreateRequest;
    path?: never;
    query?: never;
    url: '/v1/model-instances/bulk';
};
export type CreateModelInstancesBulkV1ModelInstancesBulkPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateModelInstancesBulkV1ModelInstancesBulkPostError = CreateModelInstancesBulkV1ModelInstancesBulkPostErrors[keyof CreateModelInstancesBulkV1ModelInstancesBulkPostErrors];
export type CreateModelInstancesBulkV1ModelInstancesBulkPostResponses = {
    /**
     * Successful Response
     */
    200: ModelInstanceBulkCreateResponse;
};
export type CreateModelInstancesBulkV1ModelInstancesBulkPostResponse = CreateModelInstancesBulkV1ModelInstancesBulkPostResponses[keyof CreateModelInstancesBulkV1ModelInstancesBulkPostResponses];
export type ValidateModelInstanceV1ModelInstancesTestPostData = {
    body: ModelInstanceTestRequest;
    path?: never;
    query?: never;
    url: '/v1/model-instances/test';
};
export type ValidateModelInstanceV1ModelInstancesTestPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ValidateModelInstanceV1ModelInstancesTestPostError = ValidateModelInstanceV1ModelInstancesTestPostErrors[keyof ValidateModelInstanceV1ModelInstancesTestPostErrors];
export type ValidateModelInstanceV1ModelInstancesTestPostResponses = {
    /**
     * Successful Response
     */
    200: ModelInstanceTestResponse;
};
export type ValidateModelInstanceV1ModelInstancesTestPostResponse = ValidateModelInstanceV1ModelInstancesTestPostResponses[keyof ValidateModelInstanceV1ModelInstancesTestPostResponses];
export type DeleteModelInstanceV1ModelInstancesInstanceIdDeleteData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/model-instances/{instance_id}';
};
export type DeleteModelInstanceV1ModelInstancesInstanceIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteModelInstanceV1ModelInstancesInstanceIdDeleteError = DeleteModelInstanceV1ModelInstancesInstanceIdDeleteErrors[keyof DeleteModelInstanceV1ModelInstancesInstanceIdDeleteErrors];
export type DeleteModelInstanceV1ModelInstancesInstanceIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetModelInstanceV1ModelInstancesInstanceIdGetData = {
    body?: never;
    path: {
        /**
         * Instance Id
         */
        instance_id: string;
    };
    query?: never;
    url: '/v1/model-instances/{instance_id}';
};
export type GetModelInstanceV1ModelInstancesInstanceIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetModelInstanceV1ModelInstancesInstanceIdGetError = GetModelInstanceV1ModelInstancesInstanceIdGetErrors[keyof GetModelInstanceV1ModelInstancesInstanceIdGetErrors];
export type GetModelInstanceV1ModelInstancesInstanceIdGetResponses = {
    /**
     * Successful Response
     */
    200: ModelInstanceResponse;
};
export type GetModelInstanceV1ModelInstancesInstanceIdGetResponse = GetModelInstanceV1ModelInstancesInstanceIdGetResponses[keyof GetModelInstanceV1ModelInstancesInstanceIdGetResponses];
export type ListModelSpecsV1ModelSpecsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Provider Spec Id
         */
        provider_spec_id?: string | null;
        /**
         * Is Active
         */
        is_active?: boolean | null;
    };
    url: '/v1/model-specs/';
};
export type ListModelSpecsV1ModelSpecsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListModelSpecsV1ModelSpecsGetError = ListModelSpecsV1ModelSpecsGetErrors[keyof ListModelSpecsV1ModelSpecsGetErrors];
export type ListModelSpecsV1ModelSpecsGetResponses = {
    /**
     * Response List Model Specs V1 Model Specs  Get
     *
     * Successful Response
     */
    200: Array<AgentareaApiApiV1ModelSpecsModelSpecResponse>;
};
export type ListModelSpecsV1ModelSpecsGetResponse = ListModelSpecsV1ModelSpecsGetResponses[keyof ListModelSpecsV1ModelSpecsGetResponses];
export type CreateModelSpecV1ModelSpecsPostData = {
    body: ModelSpecCreate;
    path?: never;
    query?: never;
    url: '/v1/model-specs/';
};
export type CreateModelSpecV1ModelSpecsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateModelSpecV1ModelSpecsPostError = CreateModelSpecV1ModelSpecsPostErrors[keyof CreateModelSpecV1ModelSpecsPostErrors];
export type CreateModelSpecV1ModelSpecsPostResponses = {
    /**
     * Successful Response
     */
    200: AgentareaApiApiV1ModelSpecsModelSpecResponse;
};
export type CreateModelSpecV1ModelSpecsPostResponse = CreateModelSpecV1ModelSpecsPostResponses[keyof CreateModelSpecV1ModelSpecsPostResponses];
export type ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetData = {
    body?: never;
    path: {
        /**
         * Provider Spec Id
         */
        provider_spec_id: string;
    };
    query?: {
        /**
         * Is Active
         */
        is_active?: boolean | null;
    };
    url: '/v1/model-specs/by-provider/{provider_spec_id}';
};
export type ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetError = ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetErrors[keyof ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetErrors];
export type ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetResponses = {
    /**
     * Response List Model Specs By Provider V1 Model Specs By Provider  Provider Spec Id  Get
     *
     * Successful Response
     */
    200: Array<AgentareaApiApiV1ModelSpecsModelSpecResponse>;
};
export type ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetResponse = ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetResponses[keyof ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetResponses];
export type GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetData = {
    body?: never;
    path: {
        /**
         * Provider Spec Id
         */
        provider_spec_id: string;
        /**
         * Model Name
         */
        model_name: string;
    };
    query?: never;
    url: '/v1/model-specs/by-provider/{provider_spec_id}/{model_name}';
};
export type GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetError = GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetErrors[keyof GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetErrors];
export type GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetResponses = {
    /**
     * Successful Response
     */
    200: AgentareaApiApiV1ModelSpecsModelSpecResponse;
};
export type GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetResponse = GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetResponses[keyof GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetResponses];
export type UpsertModelSpecV1ModelSpecsUpsertPostData = {
    body: ModelSpecCreate;
    path?: never;
    query?: never;
    url: '/v1/model-specs/upsert';
};
export type UpsertModelSpecV1ModelSpecsUpsertPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpsertModelSpecV1ModelSpecsUpsertPostError = UpsertModelSpecV1ModelSpecsUpsertPostErrors[keyof UpsertModelSpecV1ModelSpecsUpsertPostErrors];
export type UpsertModelSpecV1ModelSpecsUpsertPostResponses = {
    /**
     * Successful Response
     */
    200: AgentareaApiApiV1ModelSpecsModelSpecResponse;
};
export type UpsertModelSpecV1ModelSpecsUpsertPostResponse = UpsertModelSpecV1ModelSpecsUpsertPostResponses[keyof UpsertModelSpecV1ModelSpecsUpsertPostResponses];
export type DeleteModelSpecV1ModelSpecsModelSpecIdDeleteData = {
    body?: never;
    path: {
        /**
         * Model Spec Id
         */
        model_spec_id: string;
    };
    query?: never;
    url: '/v1/model-specs/{model_spec_id}';
};
export type DeleteModelSpecV1ModelSpecsModelSpecIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteModelSpecV1ModelSpecsModelSpecIdDeleteError = DeleteModelSpecV1ModelSpecsModelSpecIdDeleteErrors[keyof DeleteModelSpecV1ModelSpecsModelSpecIdDeleteErrors];
export type DeleteModelSpecV1ModelSpecsModelSpecIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetModelSpecV1ModelSpecsModelSpecIdGetData = {
    body?: never;
    path: {
        /**
         * Model Spec Id
         */
        model_spec_id: string;
    };
    query?: never;
    url: '/v1/model-specs/{model_spec_id}';
};
export type GetModelSpecV1ModelSpecsModelSpecIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetModelSpecV1ModelSpecsModelSpecIdGetError = GetModelSpecV1ModelSpecsModelSpecIdGetErrors[keyof GetModelSpecV1ModelSpecsModelSpecIdGetErrors];
export type GetModelSpecV1ModelSpecsModelSpecIdGetResponses = {
    /**
     * Successful Response
     */
    200: AgentareaApiApiV1ModelSpecsModelSpecResponse;
};
export type GetModelSpecV1ModelSpecsModelSpecIdGetResponse = GetModelSpecV1ModelSpecsModelSpecIdGetResponses[keyof GetModelSpecV1ModelSpecsModelSpecIdGetResponses];
export type UpdateModelSpecV1ModelSpecsModelSpecIdPatchData = {
    body: ModelSpecUpdate;
    path: {
        /**
         * Model Spec Id
         */
        model_spec_id: string;
    };
    query?: never;
    url: '/v1/model-specs/{model_spec_id}';
};
export type UpdateModelSpecV1ModelSpecsModelSpecIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateModelSpecV1ModelSpecsModelSpecIdPatchError = UpdateModelSpecV1ModelSpecsModelSpecIdPatchErrors[keyof UpdateModelSpecV1ModelSpecsModelSpecIdPatchErrors];
export type UpdateModelSpecV1ModelSpecsModelSpecIdPatchResponses = {
    /**
     * Successful Response
     */
    200: AgentareaApiApiV1ModelSpecsModelSpecResponse;
};
export type UpdateModelSpecV1ModelSpecsModelSpecIdPatchResponse = UpdateModelSpecV1ModelSpecsModelSpecIdPatchResponses[keyof UpdateModelSpecV1ModelSpecsModelSpecIdPatchResponses];
export type GetNetworkTopologyV1NetworkTopologyGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/network/topology';
};
export type GetNetworkTopologyV1NetworkTopologyGetResponses = {
    /**
     * Successful Response
     */
    200: NetworkTopologyResponse;
};
export type GetNetworkTopologyV1NetworkTopologyGetResponse = GetNetworkTopologyV1NetworkTopologyGetResponses[keyof GetNetworkTopologyV1NetworkTopologyGetResponses];
export type ListConnectionsV1OpenapiConnectionsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Status
         */
        status?: string | null;
        /**
         * Search
         */
        search?: string | null;
        /**
         * Limit
         */
        limit?: number;
        /**
         * Offset
         */
        offset?: number;
    };
    url: '/v1/openapi-connections/';
};
export type ListConnectionsV1OpenapiConnectionsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListConnectionsV1OpenapiConnectionsGetError = ListConnectionsV1OpenapiConnectionsGetErrors[keyof ListConnectionsV1OpenapiConnectionsGetErrors];
export type ListConnectionsV1OpenapiConnectionsGetResponses = {
    /**
     * Response List Connections V1 Openapi Connections  Get
     *
     * Successful Response
     */
    200: Array<OpenApiConnectionResponse>;
};
export type ListConnectionsV1OpenapiConnectionsGetResponse = ListConnectionsV1OpenapiConnectionsGetResponses[keyof ListConnectionsV1OpenapiConnectionsGetResponses];
export type CreateConnectionV1OpenapiConnectionsPostData = {
    body: OpenApiConnectionCreate;
    path?: never;
    query?: never;
    url: '/v1/openapi-connections/';
};
export type CreateConnectionV1OpenapiConnectionsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateConnectionV1OpenapiConnectionsPostError = CreateConnectionV1OpenapiConnectionsPostErrors[keyof CreateConnectionV1OpenapiConnectionsPostErrors];
export type CreateConnectionV1OpenapiConnectionsPostResponses = {
    /**
     * Successful Response
     */
    201: OpenApiConnectionResponse;
};
export type CreateConnectionV1OpenapiConnectionsPostResponse = CreateConnectionV1OpenapiConnectionsPostResponses[keyof CreateConnectionV1OpenapiConnectionsPostResponses];
export type PreviewSpecV1OpenapiConnectionsPreviewSpecPostData = {
    body: SpecPreviewRequest;
    path?: never;
    query?: never;
    url: '/v1/openapi-connections/preview-spec';
};
export type PreviewSpecV1OpenapiConnectionsPreviewSpecPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type PreviewSpecV1OpenapiConnectionsPreviewSpecPostError = PreviewSpecV1OpenapiConnectionsPreviewSpecPostErrors[keyof PreviewSpecV1OpenapiConnectionsPreviewSpecPostErrors];
export type PreviewSpecV1OpenapiConnectionsPreviewSpecPostResponses = {
    /**
     * Successful Response
     */
    200: SpecPreviewResponse;
};
export type PreviewSpecV1OpenapiConnectionsPreviewSpecPostResponse = PreviewSpecV1OpenapiConnectionsPreviewSpecPostResponses[keyof PreviewSpecV1OpenapiConnectionsPreviewSpecPostResponses];
export type DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteData = {
    body?: never;
    path: {
        /**
         * Connection Id
         */
        connection_id: string;
    };
    query?: never;
    url: '/v1/openapi-connections/{connection_id}';
};
export type DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteError = DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteErrors[keyof DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteErrors];
export type DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteResponse = DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteResponses[keyof DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteResponses];
export type GetConnectionV1OpenapiConnectionsConnectionIdGetData = {
    body?: never;
    path: {
        /**
         * Connection Id
         */
        connection_id: string;
    };
    query?: never;
    url: '/v1/openapi-connections/{connection_id}';
};
export type GetConnectionV1OpenapiConnectionsConnectionIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetConnectionV1OpenapiConnectionsConnectionIdGetError = GetConnectionV1OpenapiConnectionsConnectionIdGetErrors[keyof GetConnectionV1OpenapiConnectionsConnectionIdGetErrors];
export type GetConnectionV1OpenapiConnectionsConnectionIdGetResponses = {
    /**
     * Successful Response
     */
    200: OpenApiConnectionResponse;
};
export type GetConnectionV1OpenapiConnectionsConnectionIdGetResponse = GetConnectionV1OpenapiConnectionsConnectionIdGetResponses[keyof GetConnectionV1OpenapiConnectionsConnectionIdGetResponses];
export type UpdateConnectionV1OpenapiConnectionsConnectionIdPatchData = {
    body: OpenApiConnectionUpdate;
    path: {
        /**
         * Connection Id
         */
        connection_id: string;
    };
    query?: never;
    url: '/v1/openapi-connections/{connection_id}';
};
export type UpdateConnectionV1OpenapiConnectionsConnectionIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateConnectionV1OpenapiConnectionsConnectionIdPatchError = UpdateConnectionV1OpenapiConnectionsConnectionIdPatchErrors[keyof UpdateConnectionV1OpenapiConnectionsConnectionIdPatchErrors];
export type UpdateConnectionV1OpenapiConnectionsConnectionIdPatchResponses = {
    /**
     * Successful Response
     */
    200: OpenApiConnectionResponse;
};
export type UpdateConnectionV1OpenapiConnectionsConnectionIdPatchResponse = UpdateConnectionV1OpenapiConnectionsConnectionIdPatchResponses[keyof UpdateConnectionV1OpenapiConnectionsConnectionIdPatchResponses];
export type DiscoverToolsV1OpenapiConnectionsConnectionIdDiscoverToolsPostData = {
    body?: never;
    path: {
        /**
         * Connection Id
         */
        connection_id: string;
    };
    query?: never;
    url: '/v1/openapi-connections/{connection_id}/discover-tools';
};
export type DiscoverToolsV1OpenapiConnectionsConnectionIdDiscoverToolsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DiscoverToolsV1OpenapiConnectionsConnectionIdDiscoverToolsPostError = DiscoverToolsV1OpenapiConnectionsConnectionIdDiscoverToolsPostErrors[keyof DiscoverToolsV1OpenapiConnectionsConnectionIdDiscoverToolsPostErrors];
export type DiscoverToolsV1OpenapiConnectionsConnectionIdDiscoverToolsPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ListPolicyRulesV1PoliciesGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Subject Type
         */
        subject_type?: PolicySubjectType | null;
        /**
         * Subject Id
         */
        subject_id?: string | null;
        /**
         * Effect
         */
        effect?: PolicyEffect | null;
        /**
         * Target
         */
        target?: string | null;
        /**
         * Enabled
         */
        enabled?: boolean | null;
    };
    url: '/v1/policies';
};
export type ListPolicyRulesV1PoliciesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListPolicyRulesV1PoliciesGetError = ListPolicyRulesV1PoliciesGetErrors[keyof ListPolicyRulesV1PoliciesGetErrors];
export type ListPolicyRulesV1PoliciesGetResponses = {
    /**
     * Response List Policy Rules V1 Policies Get
     *
     * Successful Response
     */
    200: Array<PolicyRuleResponse>;
};
export type ListPolicyRulesV1PoliciesGetResponse = ListPolicyRulesV1PoliciesGetResponses[keyof ListPolicyRulesV1PoliciesGetResponses];
export type CreatePolicyRuleV1PoliciesPostData = {
    body: PolicyRuleCreateRequest;
    path?: never;
    query?: never;
    url: '/v1/policies';
};
export type CreatePolicyRuleV1PoliciesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreatePolicyRuleV1PoliciesPostError = CreatePolicyRuleV1PoliciesPostErrors[keyof CreatePolicyRuleV1PoliciesPostErrors];
export type CreatePolicyRuleV1PoliciesPostResponses = {
    /**
     * Successful Response
     */
    201: PolicyRuleResponse;
};
export type CreatePolicyRuleV1PoliciesPostResponse = CreatePolicyRuleV1PoliciesPostResponses[keyof CreatePolicyRuleV1PoliciesPostResponses];
export type DeletePolicyRuleV1PoliciesRuleIdDeleteData = {
    body?: never;
    path: {
        /**
         * Rule Id
         */
        rule_id: string;
    };
    query?: never;
    url: '/v1/policies/{rule_id}';
};
export type DeletePolicyRuleV1PoliciesRuleIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeletePolicyRuleV1PoliciesRuleIdDeleteError = DeletePolicyRuleV1PoliciesRuleIdDeleteErrors[keyof DeletePolicyRuleV1PoliciesRuleIdDeleteErrors];
export type DeletePolicyRuleV1PoliciesRuleIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeletePolicyRuleV1PoliciesRuleIdDeleteResponse = DeletePolicyRuleV1PoliciesRuleIdDeleteResponses[keyof DeletePolicyRuleV1PoliciesRuleIdDeleteResponses];
export type GetPolicyRuleV1PoliciesRuleIdGetData = {
    body?: never;
    path: {
        /**
         * Rule Id
         */
        rule_id: string;
    };
    query?: never;
    url: '/v1/policies/{rule_id}';
};
export type GetPolicyRuleV1PoliciesRuleIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetPolicyRuleV1PoliciesRuleIdGetError = GetPolicyRuleV1PoliciesRuleIdGetErrors[keyof GetPolicyRuleV1PoliciesRuleIdGetErrors];
export type GetPolicyRuleV1PoliciesRuleIdGetResponses = {
    /**
     * Successful Response
     */
    200: PolicyRuleResponse;
};
export type GetPolicyRuleV1PoliciesRuleIdGetResponse = GetPolicyRuleV1PoliciesRuleIdGetResponses[keyof GetPolicyRuleV1PoliciesRuleIdGetResponses];
export type UpdatePolicyRuleV1PoliciesRuleIdPatchData = {
    body: PolicyRuleUpdateRequest;
    path: {
        /**
         * Rule Id
         */
        rule_id: string;
    };
    query?: never;
    url: '/v1/policies/{rule_id}';
};
export type UpdatePolicyRuleV1PoliciesRuleIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdatePolicyRuleV1PoliciesRuleIdPatchError = UpdatePolicyRuleV1PoliciesRuleIdPatchErrors[keyof UpdatePolicyRuleV1PoliciesRuleIdPatchErrors];
export type UpdatePolicyRuleV1PoliciesRuleIdPatchResponses = {
    /**
     * Successful Response
     */
    200: PolicyRuleResponse;
};
export type UpdatePolicyRuleV1PoliciesRuleIdPatchResponse = UpdatePolicyRuleV1PoliciesRuleIdPatchResponses[keyof UpdatePolicyRuleV1PoliciesRuleIdPatchResponses];
export type ListProjectsV1ProjectsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Limit
         */
        limit?: number;
        /**
         * Offset
         */
        offset?: number;
    };
    url: '/v1/projects/';
};
export type ListProjectsV1ProjectsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListProjectsV1ProjectsGetError = ListProjectsV1ProjectsGetErrors[keyof ListProjectsV1ProjectsGetErrors];
export type ListProjectsV1ProjectsGetResponses = {
    /**
     * Response List Projects V1 Projects  Get
     *
     * Successful Response
     */
    200: Array<ProjectResponse>;
};
export type ListProjectsV1ProjectsGetResponse = ListProjectsV1ProjectsGetResponses[keyof ListProjectsV1ProjectsGetResponses];
export type CreateProjectV1ProjectsPostData = {
    body: ProjectCreate;
    path?: never;
    query?: never;
    url: '/v1/projects/';
};
export type CreateProjectV1ProjectsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateProjectV1ProjectsPostError = CreateProjectV1ProjectsPostErrors[keyof CreateProjectV1ProjectsPostErrors];
export type CreateProjectV1ProjectsPostResponses = {
    /**
     * Successful Response
     */
    201: ProjectResponse;
};
export type CreateProjectV1ProjectsPostResponse = CreateProjectV1ProjectsPostResponses[keyof CreateProjectV1ProjectsPostResponses];
export type DeleteProjectV1ProjectsProjectIdDeleteData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}';
};
export type DeleteProjectV1ProjectsProjectIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteProjectV1ProjectsProjectIdDeleteError = DeleteProjectV1ProjectsProjectIdDeleteErrors[keyof DeleteProjectV1ProjectsProjectIdDeleteErrors];
export type DeleteProjectV1ProjectsProjectIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteProjectV1ProjectsProjectIdDeleteResponse = DeleteProjectV1ProjectsProjectIdDeleteResponses[keyof DeleteProjectV1ProjectsProjectIdDeleteResponses];
export type GetProjectV1ProjectsProjectIdGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}';
};
export type GetProjectV1ProjectsProjectIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetProjectV1ProjectsProjectIdGetError = GetProjectV1ProjectsProjectIdGetErrors[keyof GetProjectV1ProjectsProjectIdGetErrors];
export type GetProjectV1ProjectsProjectIdGetResponses = {
    /**
     * Successful Response
     */
    200: ProjectResponse;
};
export type GetProjectV1ProjectsProjectIdGetResponse = GetProjectV1ProjectsProjectIdGetResponses[keyof GetProjectV1ProjectsProjectIdGetResponses];
export type UpdateProjectV1ProjectsProjectIdPatchData = {
    body: ProjectUpdate;
    path: {
        /**
         * Project Id
         */
        project_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}';
};
export type UpdateProjectV1ProjectsProjectIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateProjectV1ProjectsProjectIdPatchError = UpdateProjectV1ProjectsProjectIdPatchErrors[keyof UpdateProjectV1ProjectsProjectIdPatchErrors];
export type UpdateProjectV1ProjectsProjectIdPatchResponses = {
    /**
     * Successful Response
     */
    200: ProjectResponse;
};
export type UpdateProjectV1ProjectsProjectIdPatchResponse = UpdateProjectV1ProjectsProjectIdPatchResponses[keyof UpdateProjectV1ProjectsProjectIdPatchResponses];
export type AddAgentToProjectV1ProjectsProjectIdAgentsPostData = {
    body: AssociationBody;
    path: {
        /**
         * Project Id
         */
        project_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/agents';
};
export type AddAgentToProjectV1ProjectsProjectIdAgentsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AddAgentToProjectV1ProjectsProjectIdAgentsPostError = AddAgentToProjectV1ProjectsProjectIdAgentsPostErrors[keyof AddAgentToProjectV1ProjectsProjectIdAgentsPostErrors];
export type AddAgentToProjectV1ProjectsProjectIdAgentsPostResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type AddAgentToProjectV1ProjectsProjectIdAgentsPostResponse = AddAgentToProjectV1ProjectsProjectIdAgentsPostResponses[keyof AddAgentToProjectV1ProjectsProjectIdAgentsPostResponses];
export type RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
        /**
         * Agent Id
         */
        agent_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/agents/{agent_id}';
};
export type RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteError = RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteErrors[keyof RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteErrors];
export type RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteResponse = RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteResponses[keyof RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteResponses];
export type ListProjectFilesV1ProjectsProjectIdFilesGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/files';
};
export type ListProjectFilesV1ProjectsProjectIdFilesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListProjectFilesV1ProjectsProjectIdFilesGetError = ListProjectFilesV1ProjectsProjectIdFilesGetErrors[keyof ListProjectFilesV1ProjectsProjectIdFilesGetErrors];
export type ListProjectFilesV1ProjectsProjectIdFilesGetResponses = {
    /**
     * Successful Response
     */
    200: ProjectFileListResponse;
};
export type ListProjectFilesV1ProjectsProjectIdFilesGetResponse = ListProjectFilesV1ProjectsProjectIdFilesGetResponses[keyof ListProjectFilesV1ProjectsProjectIdFilesGetResponses];
export type UploadProjectFileV1ProjectsProjectIdFilesPostData = {
    body: BodyUploadProjectFileV1ProjectsProjectIdFilesPost;
    path: {
        /**
         * Project Id
         */
        project_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/files';
};
export type UploadProjectFileV1ProjectsProjectIdFilesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UploadProjectFileV1ProjectsProjectIdFilesPostError = UploadProjectFileV1ProjectsProjectIdFilesPostErrors[keyof UploadProjectFileV1ProjectsProjectIdFilesPostErrors];
export type UploadProjectFileV1ProjectsProjectIdFilesPostResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type UploadProjectFileV1ProjectsProjectIdFilesPostResponse = UploadProjectFileV1ProjectsProjectIdFilesPostResponses[keyof UploadProjectFileV1ProjectsProjectIdFilesPostResponses];
export type StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
        /**
         * File Path
         */
        file_path: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/files/download/{file_path}';
};
export type StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetError = StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetErrors[keyof StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetErrors];
export type StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
        /**
         * File Path
         */
        file_path: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/files/{file_path}';
};
export type DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteError = DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteErrors[keyof DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteErrors];
export type DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteResponse = DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteResponses[keyof DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteResponses];
export type DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
        /**
         * File Path
         */
        file_path: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/files/{file_path}';
};
export type DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetError = DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetErrors[keyof DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetErrors];
export type DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetResponses = {
    /**
     * Successful Response
     */
    200: ProjectFileDownloadResponse;
};
export type DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetResponse = DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetResponses[keyof DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetResponses];
export type AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostData = {
    body: AssociationBody;
    path: {
        /**
         * Project Id
         */
        project_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/mcp-instances';
};
export type AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostError = AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostErrors[keyof AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostErrors];
export type AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostResponse = AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostResponses[keyof AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostResponses];
export type RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
        /**
         * Mcp Instance Id
         */
        mcp_instance_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/mcp-instances/{mcp_instance_id}';
};
export type RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteError = RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteErrors[keyof RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteErrors];
export type RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteResponse = RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteResponses[keyof RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteResponses];
export type AddSkillToProjectV1ProjectsProjectIdSkillsPostData = {
    body: AssociationBody;
    path: {
        /**
         * Project Id
         */
        project_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/skills';
};
export type AddSkillToProjectV1ProjectsProjectIdSkillsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AddSkillToProjectV1ProjectsProjectIdSkillsPostError = AddSkillToProjectV1ProjectsProjectIdSkillsPostErrors[keyof AddSkillToProjectV1ProjectsProjectIdSkillsPostErrors];
export type AddSkillToProjectV1ProjectsProjectIdSkillsPostResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type AddSkillToProjectV1ProjectsProjectIdSkillsPostResponse = AddSkillToProjectV1ProjectsProjectIdSkillsPostResponses[keyof AddSkillToProjectV1ProjectsProjectIdSkillsPostResponses];
export type RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: string;
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/projects/{project_id}/skills/{skill_id}';
};
export type RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteError = RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteErrors[keyof RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteErrors];
export type RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteResponse = RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteResponses[keyof RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteResponses];
export type ListProviderConfigsV1ProviderConfigsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Provider Spec Id
         */
        provider_spec_id?: string | null;
        /**
         * Is Active
         */
        is_active?: boolean | null;
    };
    url: '/v1/provider-configs/';
};
export type ListProviderConfigsV1ProviderConfigsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListProviderConfigsV1ProviderConfigsGetError = ListProviderConfigsV1ProviderConfigsGetErrors[keyof ListProviderConfigsV1ProviderConfigsGetErrors];
export type ListProviderConfigsV1ProviderConfigsGetResponses = {
    /**
     * Response List Provider Configs V1 Provider Configs  Get
     *
     * Successful Response
     */
    200: Array<ProviderConfigResponse>;
};
export type ListProviderConfigsV1ProviderConfigsGetResponse = ListProviderConfigsV1ProviderConfigsGetResponses[keyof ListProviderConfigsV1ProviderConfigsGetResponses];
export type CreateProviderConfigV1ProviderConfigsPostData = {
    body: ProviderConfigCreate;
    path?: never;
    query?: never;
    url: '/v1/provider-configs/';
};
export type CreateProviderConfigV1ProviderConfigsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateProviderConfigV1ProviderConfigsPostError = CreateProviderConfigV1ProviderConfigsPostErrors[keyof CreateProviderConfigV1ProviderConfigsPostErrors];
export type CreateProviderConfigV1ProviderConfigsPostResponses = {
    /**
     * Successful Response
     */
    200: ProviderConfigResponse;
};
export type CreateProviderConfigV1ProviderConfigsPostResponse = CreateProviderConfigV1ProviderConfigsPostResponses[keyof CreateProviderConfigV1ProviderConfigsPostResponses];
export type GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetData = {
    body?: never;
    path: {
        /**
         * Provider Key
         */
        provider_key: string;
    };
    query?: never;
    url: '/v1/provider-configs/admin/{provider_key}/logo';
};
export type GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetError = GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetErrors[keyof GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetErrors];
export type GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostData = {
    body: DiscoverPreviewRequest;
    path?: never;
    query?: never;
    url: '/v1/provider-configs/discover-preview';
};
export type DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostError = DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostErrors[keyof DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostErrors];
export type DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostResponses = {
    /**
     * Successful Response
     */
    200: DiscoverPreviewResponse;
};
export type DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostResponse = DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostResponses[keyof DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostResponses];
export type ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Provider Spec Id
         */
        provider_spec_id?: string | null;
        /**
         * Is Active
         */
        is_active?: boolean | null;
    };
    url: '/v1/provider-configs/with-instances';
};
export type ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetError = ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetErrors[keyof ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetErrors];
export type ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetResponses = {
    /**
     * Response List Provider Configs With Instances V1 Provider Configs With Instances Get
     *
     * Successful Response
     */
    200: Array<ProviderConfigResponse>;
};
export type ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetResponse = ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetResponses[keyof ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetResponses];
export type DeleteProviderConfigV1ProviderConfigsConfigIdDeleteData = {
    body?: never;
    path: {
        /**
         * Config Id
         */
        config_id: string;
    };
    query?: never;
    url: '/v1/provider-configs/{config_id}';
};
export type DeleteProviderConfigV1ProviderConfigsConfigIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteProviderConfigV1ProviderConfigsConfigIdDeleteError = DeleteProviderConfigV1ProviderConfigsConfigIdDeleteErrors[keyof DeleteProviderConfigV1ProviderConfigsConfigIdDeleteErrors];
export type DeleteProviderConfigV1ProviderConfigsConfigIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetProviderConfigV1ProviderConfigsConfigIdGetData = {
    body?: never;
    path: {
        /**
         * Config Id
         */
        config_id: string;
    };
    query?: never;
    url: '/v1/provider-configs/{config_id}';
};
export type GetProviderConfigV1ProviderConfigsConfigIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetProviderConfigV1ProviderConfigsConfigIdGetError = GetProviderConfigV1ProviderConfigsConfigIdGetErrors[keyof GetProviderConfigV1ProviderConfigsConfigIdGetErrors];
export type GetProviderConfigV1ProviderConfigsConfigIdGetResponses = {
    /**
     * Successful Response
     */
    200: ProviderConfigResponse;
};
export type GetProviderConfigV1ProviderConfigsConfigIdGetResponse = GetProviderConfigV1ProviderConfigsConfigIdGetResponses[keyof GetProviderConfigV1ProviderConfigsConfigIdGetResponses];
export type PatchProviderConfigV1ProviderConfigsConfigIdPatchData = {
    body: ProviderConfigUpdate;
    path: {
        /**
         * Config Id
         */
        config_id: string;
    };
    query?: never;
    url: '/v1/provider-configs/{config_id}';
};
export type PatchProviderConfigV1ProviderConfigsConfigIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type PatchProviderConfigV1ProviderConfigsConfigIdPatchError = PatchProviderConfigV1ProviderConfigsConfigIdPatchErrors[keyof PatchProviderConfigV1ProviderConfigsConfigIdPatchErrors];
export type PatchProviderConfigV1ProviderConfigsConfigIdPatchResponses = {
    /**
     * Successful Response
     */
    200: ProviderConfigResponse;
};
export type PatchProviderConfigV1ProviderConfigsConfigIdPatchResponse = PatchProviderConfigV1ProviderConfigsConfigIdPatchResponses[keyof PatchProviderConfigV1ProviderConfigsConfigIdPatchResponses];
export type UpdateProviderConfigV1ProviderConfigsConfigIdPutData = {
    body: ProviderConfigUpdate;
    path: {
        /**
         * Config Id
         */
        config_id: string;
    };
    query?: never;
    url: '/v1/provider-configs/{config_id}';
};
export type UpdateProviderConfigV1ProviderConfigsConfigIdPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateProviderConfigV1ProviderConfigsConfigIdPutError = UpdateProviderConfigV1ProviderConfigsConfigIdPutErrors[keyof UpdateProviderConfigV1ProviderConfigsConfigIdPutErrors];
export type UpdateProviderConfigV1ProviderConfigsConfigIdPutResponses = {
    /**
     * Successful Response
     */
    200: ProviderConfigResponse;
};
export type UpdateProviderConfigV1ProviderConfigsConfigIdPutResponse = UpdateProviderConfigV1ProviderConfigsConfigIdPutResponses[keyof UpdateProviderConfigV1ProviderConfigsConfigIdPutResponses];
export type DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostData = {
    body?: never;
    path: {
        /**
         * Config Id
         */
        config_id: string;
    };
    query?: never;
    url: '/v1/provider-configs/{config_id}/discover';
};
export type DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostError = DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostErrors[keyof DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostErrors];
export type DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostResponses = {
    /**
     * Successful Response
     */
    200: DiscoveryResponse;
};
export type DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostResponse = DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostResponses[keyof DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostResponses];
export type ListProviderSpecsV1ProviderSpecsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Is Builtin
         */
        is_builtin?: boolean | null;
    };
    url: '/v1/provider-specs/';
};
export type ListProviderSpecsV1ProviderSpecsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListProviderSpecsV1ProviderSpecsGetError = ListProviderSpecsV1ProviderSpecsGetErrors[keyof ListProviderSpecsV1ProviderSpecsGetErrors];
export type ListProviderSpecsV1ProviderSpecsGetResponses = {
    /**
     * Response List Provider Specs V1 Provider Specs  Get
     *
     * Successful Response
     */
    200: Array<ProviderSpecResponse>;
};
export type ListProviderSpecsV1ProviderSpecsGetResponse = ListProviderSpecsV1ProviderSpecsGetResponses[keyof ListProviderSpecsV1ProviderSpecsGetResponses];
export type GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetData = {
    body?: never;
    path: {
        /**
         * Provider Key
         */
        provider_key: string;
    };
    query?: never;
    url: '/v1/provider-specs/by-key/{provider_key}';
};
export type GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetError = GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetErrors[keyof GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetErrors];
export type GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetResponses = {
    /**
     * Successful Response
     */
    200: ProviderSpecWithModelsResponse;
};
export type GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetResponse = GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetResponses[keyof GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetResponses];
export type ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Is Builtin
         */
        is_builtin?: boolean | null;
    };
    url: '/v1/provider-specs/with-models';
};
export type ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetError = ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetErrors[keyof ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetErrors];
export type ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetResponses = {
    /**
     * Response List Provider Specs With Models V1 Provider Specs With Models Get
     *
     * Successful Response
     */
    200: Array<ProviderSpecWithModelsResponse>;
};
export type ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetResponse = ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetResponses[keyof ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetResponses];
export type GetProviderSpecV1ProviderSpecsProviderSpecIdGetData = {
    body?: never;
    path: {
        /**
         * Provider Spec Id
         */
        provider_spec_id: string;
    };
    query?: never;
    url: '/v1/provider-specs/{provider_spec_id}';
};
export type GetProviderSpecV1ProviderSpecsProviderSpecIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetProviderSpecV1ProviderSpecsProviderSpecIdGetError = GetProviderSpecV1ProviderSpecsProviderSpecIdGetErrors[keyof GetProviderSpecV1ProviderSpecsProviderSpecIdGetErrors];
export type GetProviderSpecV1ProviderSpecsProviderSpecIdGetResponses = {
    /**
     * Successful Response
     */
    200: ProviderSpecWithModelsResponse;
};
export type GetProviderSpecV1ProviderSpecsProviderSpecIdGetResponse = GetProviderSpecV1ProviderSpecsProviderSpecIdGetResponses[keyof GetProviderSpecV1ProviderSpecsProviderSpecIdGetResponses];
export type ListRegistriesV1RegistriesGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Active Only
         */
        active_only?: boolean;
        /**
         * Registry Type
         */
        registry_type?: string | null;
    };
    url: '/v1/registries/';
};
export type ListRegistriesV1RegistriesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListRegistriesV1RegistriesGetError = ListRegistriesV1RegistriesGetErrors[keyof ListRegistriesV1RegistriesGetErrors];
export type ListRegistriesV1RegistriesGetResponses = {
    /**
     * Response List Registries V1 Registries  Get
     *
     * Successful Response
     */
    200: Array<RegistryResponse>;
};
export type ListRegistriesV1RegistriesGetResponse = ListRegistriesV1RegistriesGetResponses[keyof ListRegistriesV1RegistriesGetResponses];
export type CreateRegistryV1RegistriesPostData = {
    body: RegistryCreate;
    path?: never;
    query?: never;
    url: '/v1/registries/';
};
export type CreateRegistryV1RegistriesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateRegistryV1RegistriesPostError = CreateRegistryV1RegistriesPostErrors[keyof CreateRegistryV1RegistriesPostErrors];
export type CreateRegistryV1RegistriesPostResponses = {
    /**
     * Successful Response
     */
    200: RegistryResponse;
};
export type CreateRegistryV1RegistriesPostResponse = CreateRegistryV1RegistriesPostResponses[keyof CreateRegistryV1RegistriesPostResponses];
export type GetCatalogItemV1RegistriesCatalogItemsItemIdGetData = {
    body?: never;
    path: {
        /**
         * Item Id
         */
        item_id: string;
    };
    query?: never;
    url: '/v1/registries/catalog/items/{item_id}';
};
export type GetCatalogItemV1RegistriesCatalogItemsItemIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetCatalogItemV1RegistriesCatalogItemsItemIdGetError = GetCatalogItemV1RegistriesCatalogItemsItemIdGetErrors[keyof GetCatalogItemV1RegistriesCatalogItemsItemIdGetErrors];
export type GetCatalogItemV1RegistriesCatalogItemsItemIdGetResponses = {
    /**
     * Successful Response
     */
    200: RegistryItemResponse;
};
export type GetCatalogItemV1RegistriesCatalogItemsItemIdGetResponse = GetCatalogItemV1RegistriesCatalogItemsItemIdGetResponses[keyof GetCatalogItemV1RegistriesCatalogItemsItemIdGetResponses];
export type UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostData = {
    body?: never;
    path: {
        /**
         * Item Id
         */
        item_id: string;
    };
    query?: never;
    url: '/v1/registries/catalog/items/{item_id}/update';
};
export type UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostError = UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostErrors[keyof UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostErrors];
export type UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type SearchCatalogV1RegistriesCatalogSearchGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Q
         *
         * Search query
         */
        q?: string | null;
        /**
         * Tag
         */
        tag?: string | null;
        /**
         * Update Available
         */
        update_available?: boolean | null;
        /**
         * Limit
         */
        limit?: number;
        /**
         * Offset
         */
        offset?: number;
    };
    url: '/v1/registries/catalog/search';
};
export type SearchCatalogV1RegistriesCatalogSearchGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type SearchCatalogV1RegistriesCatalogSearchGetError = SearchCatalogV1RegistriesCatalogSearchGetErrors[keyof SearchCatalogV1RegistriesCatalogSearchGetErrors];
export type SearchCatalogV1RegistriesCatalogSearchGetResponses = {
    /**
     * Response Search Catalog V1 Registries Catalog Search Get
     *
     * Successful Response
     */
    200: Array<RegistryItemResponse>;
};
export type SearchCatalogV1RegistriesCatalogSearchGetResponse = SearchCatalogV1RegistriesCatalogSearchGetResponses[keyof SearchCatalogV1RegistriesCatalogSearchGetResponses];
export type DeleteRegistryV1RegistriesRegistryIdDeleteData = {
    body?: never;
    path: {
        /**
         * Registry Id
         */
        registry_id: string;
    };
    query?: never;
    url: '/v1/registries/{registry_id}';
};
export type DeleteRegistryV1RegistriesRegistryIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteRegistryV1RegistriesRegistryIdDeleteError = DeleteRegistryV1RegistriesRegistryIdDeleteErrors[keyof DeleteRegistryV1RegistriesRegistryIdDeleteErrors];
export type DeleteRegistryV1RegistriesRegistryIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetRegistryV1RegistriesRegistryIdGetData = {
    body?: never;
    path: {
        /**
         * Registry Id
         */
        registry_id: string;
    };
    query?: never;
    url: '/v1/registries/{registry_id}';
};
export type GetRegistryV1RegistriesRegistryIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetRegistryV1RegistriesRegistryIdGetError = GetRegistryV1RegistriesRegistryIdGetErrors[keyof GetRegistryV1RegistriesRegistryIdGetErrors];
export type GetRegistryV1RegistriesRegistryIdGetResponses = {
    /**
     * Successful Response
     */
    200: RegistryResponse;
};
export type GetRegistryV1RegistriesRegistryIdGetResponse = GetRegistryV1RegistriesRegistryIdGetResponses[keyof GetRegistryV1RegistriesRegistryIdGetResponses];
export type UpdateRegistryV1RegistriesRegistryIdPatchData = {
    body: RegistryUpdate;
    path: {
        /**
         * Registry Id
         */
        registry_id: string;
    };
    query?: never;
    url: '/v1/registries/{registry_id}';
};
export type UpdateRegistryV1RegistriesRegistryIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateRegistryV1RegistriesRegistryIdPatchError = UpdateRegistryV1RegistriesRegistryIdPatchErrors[keyof UpdateRegistryV1RegistriesRegistryIdPatchErrors];
export type UpdateRegistryV1RegistriesRegistryIdPatchResponses = {
    /**
     * Successful Response
     */
    200: RegistryResponse;
};
export type UpdateRegistryV1RegistriesRegistryIdPatchResponse = UpdateRegistryV1RegistriesRegistryIdPatchResponses[keyof UpdateRegistryV1RegistriesRegistryIdPatchResponses];
export type ListRegistryItemsV1RegistriesRegistryIdItemsGetData = {
    body?: never;
    path: {
        /**
         * Registry Id
         */
        registry_id: string;
    };
    query?: {
        /**
         * Limit
         */
        limit?: number;
        /**
         * Offset
         */
        offset?: number;
    };
    url: '/v1/registries/{registry_id}/items';
};
export type ListRegistryItemsV1RegistriesRegistryIdItemsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListRegistryItemsV1RegistriesRegistryIdItemsGetError = ListRegistryItemsV1RegistriesRegistryIdItemsGetErrors[keyof ListRegistryItemsV1RegistriesRegistryIdItemsGetErrors];
export type ListRegistryItemsV1RegistriesRegistryIdItemsGetResponses = {
    /**
     * Response List Registry Items V1 Registries  Registry Id  Items Get
     *
     * Successful Response
     */
    200: Array<RegistryItemResponse>;
};
export type ListRegistryItemsV1RegistriesRegistryIdItemsGetResponse = ListRegistryItemsV1RegistriesRegistryIdItemsGetResponses[keyof ListRegistryItemsV1RegistriesRegistryIdItemsGetResponses];
export type SyncRegistryV1RegistriesRegistryIdSyncPostData = {
    body?: never;
    path: {
        /**
         * Registry Id
         */
        registry_id: string;
    };
    query?: never;
    url: '/v1/registries/{registry_id}/sync';
};
export type SyncRegistryV1RegistriesRegistryIdSyncPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type SyncRegistryV1RegistriesRegistryIdSyncPostError = SyncRegistryV1RegistriesRegistryIdSyncPostErrors[keyof SyncRegistryV1RegistriesRegistryIdSyncPostErrors];
export type SyncRegistryV1RegistriesRegistryIdSyncPostResponses = {
    /**
     * Successful Response
     */
    200: AgentareaApiApiV1RegistriesSyncResponse;
};
export type SyncRegistryV1RegistriesRegistryIdSyncPostResponse = SyncRegistryV1RegistriesRegistryIdSyncPostResponses[keyof SyncRegistryV1RegistriesRegistryIdSyncPostResponses];
export type UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostData = {
    body?: never;
    path: {
        /**
         * Registry Id
         */
        registry_id: string;
    };
    query?: never;
    url: '/v1/registries/{registry_id}/update-all';
};
export type UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostError = UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostErrors[keyof UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostErrors];
export type UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostResponses = {
    /**
     * Successful Response
     */
    200: UpdateAllResponse;
};
export type UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostResponse = UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostResponses[keyof UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostResponses];
export type ListSandboxesV1SandboxesGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/sandboxes';
};
export type ListSandboxesV1SandboxesGetResponses = {
    /**
     * Successful Response
     */
    200: SandboxListResponse;
};
export type ListSandboxesV1SandboxesGetResponse = ListSandboxesV1SandboxesGetResponses[keyof ListSandboxesV1SandboxesGetResponses];
export type ListSecretsV1SecretsGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/secrets';
};
export type ListSecretsV1SecretsGetResponses = {
    /**
     * Response List Secrets V1 Secrets Get
     *
     * Successful Response
     */
    200: Array<SecretResponse>;
};
export type ListSecretsV1SecretsGetResponse = ListSecretsV1SecretsGetResponses[keyof ListSecretsV1SecretsGetResponses];
export type CreateSecretV1SecretsPostData = {
    body: SecretCreate;
    path?: never;
    query?: never;
    url: '/v1/secrets';
};
export type CreateSecretV1SecretsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateSecretV1SecretsPostError = CreateSecretV1SecretsPostErrors[keyof CreateSecretV1SecretsPostErrors];
export type CreateSecretV1SecretsPostResponses = {
    /**
     * Successful Response
     */
    201: SecretResponse;
};
export type CreateSecretV1SecretsPostResponse = CreateSecretV1SecretsPostResponses[keyof CreateSecretV1SecretsPostResponses];
export type DeleteSecretV1SecretsSecretIdDeleteData = {
    body?: never;
    path: {
        /**
         * Secret Id
         */
        secret_id: string;
    };
    query?: never;
    url: '/v1/secrets/{secret_id}';
};
export type DeleteSecretV1SecretsSecretIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteSecretV1SecretsSecretIdDeleteError = DeleteSecretV1SecretsSecretIdDeleteErrors[keyof DeleteSecretV1SecretsSecretIdDeleteErrors];
export type DeleteSecretV1SecretsSecretIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteSecretV1SecretsSecretIdDeleteResponse = DeleteSecretV1SecretsSecretIdDeleteResponses[keyof DeleteSecretV1SecretsSecretIdDeleteResponses];
export type GetSecretV1SecretsSecretIdGetData = {
    body?: never;
    path: {
        /**
         * Secret Id
         */
        secret_id: string;
    };
    query?: never;
    url: '/v1/secrets/{secret_id}';
};
export type GetSecretV1SecretsSecretIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetSecretV1SecretsSecretIdGetError = GetSecretV1SecretsSecretIdGetErrors[keyof GetSecretV1SecretsSecretIdGetErrors];
export type GetSecretV1SecretsSecretIdGetResponses = {
    /**
     * Successful Response
     */
    200: SecretResponse;
};
export type GetSecretV1SecretsSecretIdGetResponse = GetSecretV1SecretsSecretIdGetResponses[keyof GetSecretV1SecretsSecretIdGetResponses];
export type UpdateSecretDescriptionV1SecretsSecretIdPatchData = {
    body: SecretDescriptionUpdate;
    path: {
        /**
         * Secret Id
         */
        secret_id: string;
    };
    query?: never;
    url: '/v1/secrets/{secret_id}';
};
export type UpdateSecretDescriptionV1SecretsSecretIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateSecretDescriptionV1SecretsSecretIdPatchError = UpdateSecretDescriptionV1SecretsSecretIdPatchErrors[keyof UpdateSecretDescriptionV1SecretsSecretIdPatchErrors];
export type UpdateSecretDescriptionV1SecretsSecretIdPatchResponses = {
    /**
     * Successful Response
     */
    200: SecretResponse;
};
export type UpdateSecretDescriptionV1SecretsSecretIdPatchResponse = UpdateSecretDescriptionV1SecretsSecretIdPatchResponses[keyof UpdateSecretDescriptionV1SecretsSecretIdPatchResponses];
export type RotateSecretV1SecretsSecretIdValuePutData = {
    body: SecretValueUpdate;
    path: {
        /**
         * Secret Id
         */
        secret_id: string;
    };
    query?: never;
    url: '/v1/secrets/{secret_id}/value';
};
export type RotateSecretV1SecretsSecretIdValuePutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RotateSecretV1SecretsSecretIdValuePutError = RotateSecretV1SecretsSecretIdValuePutErrors[keyof RotateSecretV1SecretsSecretIdValuePutErrors];
export type RotateSecretV1SecretsSecretIdValuePutResponses = {
    /**
     * Successful Response
     */
    200: SecretResponse;
};
export type RotateSecretV1SecretsSecretIdValuePutResponse = RotateSecretV1SecretsSecretIdValuePutResponses[keyof RotateSecretV1SecretsSecretIdValuePutResponses];
export type ListCollectionsV1SkillCollectionsGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/skill-collections/';
};
export type ListCollectionsV1SkillCollectionsGetResponses = {
    /**
     * Response List Collections V1 Skill Collections  Get
     *
     * Successful Response
     */
    200: Array<CollectionSummaryResponse>;
};
export type ListCollectionsV1SkillCollectionsGetResponse = ListCollectionsV1SkillCollectionsGetResponses[keyof ListCollectionsV1SkillCollectionsGetResponses];
export type CreateCollectionV1SkillCollectionsPostData = {
    body: CollectionCreateRequest;
    path?: never;
    query?: never;
    url: '/v1/skill-collections/';
};
export type CreateCollectionV1SkillCollectionsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateCollectionV1SkillCollectionsPostError = CreateCollectionV1SkillCollectionsPostErrors[keyof CreateCollectionV1SkillCollectionsPostErrors];
export type CreateCollectionV1SkillCollectionsPostResponses = {
    /**
     * Successful Response
     */
    201: CollectionSummaryResponse;
};
export type CreateCollectionV1SkillCollectionsPostResponse = CreateCollectionV1SkillCollectionsPostResponses[keyof CreateCollectionV1SkillCollectionsPostResponses];
export type DeleteCollectionV1SkillCollectionsCollectionIdDeleteData = {
    body?: never;
    path: {
        /**
         * Collection Id
         */
        collection_id: string;
    };
    query?: never;
    url: '/v1/skill-collections/{collection_id}';
};
export type DeleteCollectionV1SkillCollectionsCollectionIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteCollectionV1SkillCollectionsCollectionIdDeleteError = DeleteCollectionV1SkillCollectionsCollectionIdDeleteErrors[keyof DeleteCollectionV1SkillCollectionsCollectionIdDeleteErrors];
export type DeleteCollectionV1SkillCollectionsCollectionIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteCollectionV1SkillCollectionsCollectionIdDeleteResponse = DeleteCollectionV1SkillCollectionsCollectionIdDeleteResponses[keyof DeleteCollectionV1SkillCollectionsCollectionIdDeleteResponses];
export type GetCollectionV1SkillCollectionsCollectionIdGetData = {
    body?: never;
    path: {
        /**
         * Collection Id
         */
        collection_id: string;
    };
    query?: never;
    url: '/v1/skill-collections/{collection_id}';
};
export type GetCollectionV1SkillCollectionsCollectionIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetCollectionV1SkillCollectionsCollectionIdGetError = GetCollectionV1SkillCollectionsCollectionIdGetErrors[keyof GetCollectionV1SkillCollectionsCollectionIdGetErrors];
export type GetCollectionV1SkillCollectionsCollectionIdGetResponses = {
    /**
     * Successful Response
     */
    200: CollectionDetailResponse;
};
export type GetCollectionV1SkillCollectionsCollectionIdGetResponse = GetCollectionV1SkillCollectionsCollectionIdGetResponses[keyof GetCollectionV1SkillCollectionsCollectionIdGetResponses];
export type UpdateCollectionV1SkillCollectionsCollectionIdPutData = {
    body: CollectionUpdateRequest;
    path: {
        /**
         * Collection Id
         */
        collection_id: string;
    };
    query?: never;
    url: '/v1/skill-collections/{collection_id}';
};
export type UpdateCollectionV1SkillCollectionsCollectionIdPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateCollectionV1SkillCollectionsCollectionIdPutError = UpdateCollectionV1SkillCollectionsCollectionIdPutErrors[keyof UpdateCollectionV1SkillCollectionsCollectionIdPutErrors];
export type UpdateCollectionV1SkillCollectionsCollectionIdPutResponses = {
    /**
     * Successful Response
     */
    200: CollectionSummaryResponse;
};
export type UpdateCollectionV1SkillCollectionsCollectionIdPutResponse = UpdateCollectionV1SkillCollectionsCollectionIdPutResponses[keyof UpdateCollectionV1SkillCollectionsCollectionIdPutResponses];
export type AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostData = {
    body: AddSkillRequest;
    path: {
        /**
         * Collection Id
         */
        collection_id: string;
    };
    query?: never;
    url: '/v1/skill-collections/{collection_id}/skills';
};
export type AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostError = AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostErrors[keyof AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostErrors];
export type AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostResponse = AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostResponses[keyof AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostResponses];
export type RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteData = {
    body?: never;
    path: {
        /**
         * Collection Id
         */
        collection_id: string;
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skill-collections/{collection_id}/skills/{skill_id}';
};
export type RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteError = RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteErrors[keyof RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteErrors];
export type RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteResponse = RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteResponses[keyof RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteResponses];
export type ListSkillsV1SkillsGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Source Type
         *
         * Filter by source type
         */
        source_type?: string | null;
        /**
         * Network Scope
         *
         * Filter by network scope
         */
        network_scope?: string | null;
        /**
         * From Registry
         *
         * Filter registry-created skills
         */
        from_registry?: boolean | null;
        /**
         * Page
         */
        page?: number;
        /**
         * Page Size
         */
        page_size?: number;
        /**
         * Search
         */
        search?: string | null;
    };
    url: '/v1/skills';
};
export type ListSkillsV1SkillsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListSkillsV1SkillsGetError = ListSkillsV1SkillsGetErrors[keyof ListSkillsV1SkillsGetErrors];
export type ListSkillsV1SkillsGetResponses = {
    /**
     * Successful Response
     */
    200: PaginatedResponseSkillResponse;
};
export type ListSkillsV1SkillsGetResponse = ListSkillsV1SkillsGetResponses[keyof ListSkillsV1SkillsGetResponses];
export type CreateSkillV1SkillsPostData = {
    body: SkillCreateRequest;
    path?: never;
    query?: never;
    url: '/v1/skills';
};
export type CreateSkillV1SkillsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateSkillV1SkillsPostError = CreateSkillV1SkillsPostErrors[keyof CreateSkillV1SkillsPostErrors];
export type CreateSkillV1SkillsPostResponses = {
    /**
     * Successful Response
     */
    200: SkillResponse;
};
export type CreateSkillV1SkillsPostResponse = CreateSkillV1SkillsPostResponses[keyof CreateSkillV1SkillsPostResponses];
export type UploadSkillV1SkillsUploadPostData = {
    body: BodyUploadSkillV1SkillsUploadPost;
    path?: never;
    query?: {
        /**
         * Name
         */
        name?: string | null;
        /**
         * Description
         */
        description?: string | null;
    };
    url: '/v1/skills/upload';
};
export type UploadSkillV1SkillsUploadPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UploadSkillV1SkillsUploadPostError = UploadSkillV1SkillsUploadPostErrors[keyof UploadSkillV1SkillsUploadPostErrors];
export type UploadSkillV1SkillsUploadPostResponses = {
    /**
     * Successful Response
     */
    200: SkillResponse;
};
export type UploadSkillV1SkillsUploadPostResponse = UploadSkillV1SkillsUploadPostResponses[keyof UploadSkillV1SkillsUploadPostResponses];
export type DeleteSkillV1SkillsSkillIdDeleteData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}';
};
export type DeleteSkillV1SkillsSkillIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteSkillV1SkillsSkillIdDeleteError = DeleteSkillV1SkillsSkillIdDeleteErrors[keyof DeleteSkillV1SkillsSkillIdDeleteErrors];
export type DeleteSkillV1SkillsSkillIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetSkillV1SkillsSkillIdGetData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}';
};
export type GetSkillV1SkillsSkillIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetSkillV1SkillsSkillIdGetError = GetSkillV1SkillsSkillIdGetErrors[keyof GetSkillV1SkillsSkillIdGetErrors];
export type GetSkillV1SkillsSkillIdGetResponses = {
    /**
     * Successful Response
     */
    200: SkillResponse;
};
export type GetSkillV1SkillsSkillIdGetResponse = GetSkillV1SkillsSkillIdGetResponses[keyof GetSkillV1SkillsSkillIdGetResponses];
export type UpdateSkillV1SkillsSkillIdPutData = {
    body: SkillUpdateRequest;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}';
};
export type UpdateSkillV1SkillsSkillIdPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateSkillV1SkillsSkillIdPutError = UpdateSkillV1SkillsSkillIdPutErrors[keyof UpdateSkillV1SkillsSkillIdPutErrors];
export type UpdateSkillV1SkillsSkillIdPutResponses = {
    /**
     * Successful Response
     */
    200: SkillResponse;
};
export type UpdateSkillV1SkillsSkillIdPutResponse = UpdateSkillV1SkillsSkillIdPutResponses[keyof UpdateSkillV1SkillsSkillIdPutResponses];
export type GetSkillContentV1SkillsSkillIdContentGetData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}/content';
};
export type GetSkillContentV1SkillsSkillIdContentGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetSkillContentV1SkillsSkillIdContentGetError = GetSkillContentV1SkillsSkillIdContentGetErrors[keyof GetSkillContentV1SkillsSkillIdContentGetErrors];
export type GetSkillContentV1SkillsSkillIdContentGetResponses = {
    /**
     * Successful Response
     */
    200: SkillContentResponse;
};
export type GetSkillContentV1SkillsSkillIdContentGetResponse = GetSkillContentV1SkillsSkillIdContentGetResponses[keyof GetSkillContentV1SkillsSkillIdContentGetResponses];
export type ListSkillFilesV1SkillsSkillIdFilesGetData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: {
        /**
         * Include Urls
         */
        include_urls?: boolean;
    };
    url: '/v1/skills/{skill_id}/files';
};
export type ListSkillFilesV1SkillsSkillIdFilesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListSkillFilesV1SkillsSkillIdFilesGetError = ListSkillFilesV1SkillsSkillIdFilesGetErrors[keyof ListSkillFilesV1SkillsSkillIdFilesGetErrors];
export type ListSkillFilesV1SkillsSkillIdFilesGetResponses = {
    /**
     * Successful Response
     */
    200: SkillFilesResponse;
};
export type ListSkillFilesV1SkillsSkillIdFilesGetResponse = ListSkillFilesV1SkillsSkillIdFilesGetResponses[keyof ListSkillFilesV1SkillsSkillIdFilesGetResponses];
export type GetSkillFileV1SkillsSkillIdFilesPathGetData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
        /**
         * Path
         */
        path: string;
    };
    query?: {
        /**
         * Redirect
         */
        redirect?: boolean;
    };
    url: '/v1/skills/{skill_id}/files/{path}';
};
export type GetSkillFileV1SkillsSkillIdFilesPathGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetSkillFileV1SkillsSkillIdFilesPathGetError = GetSkillFileV1SkillsSkillIdFilesPathGetErrors[keyof GetSkillFileV1SkillsSkillIdFilesPathGetErrors];
export type GetSkillFileV1SkillsSkillIdFilesPathGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type FlattenSkillMembersV1SkillsSkillIdFlattenGetData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}/flatten';
};
export type FlattenSkillMembersV1SkillsSkillIdFlattenGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type FlattenSkillMembersV1SkillsSkillIdFlattenGetError = FlattenSkillMembersV1SkillsSkillIdFlattenGetErrors[keyof FlattenSkillMembersV1SkillsSkillIdFlattenGetErrors];
export type FlattenSkillMembersV1SkillsSkillIdFlattenGetResponses = {
    /**
     * Response Flatten Skill Members V1 Skills  Skill Id  Flatten Get
     *
     * Successful Response
     */
    200: Array<string>;
};
export type FlattenSkillMembersV1SkillsSkillIdFlattenGetResponse = FlattenSkillMembersV1SkillsSkillIdFlattenGetResponses[keyof FlattenSkillMembersV1SkillsSkillIdFlattenGetResponses];
export type InstallSkillV1SkillsSkillIdInstallPostData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}/install';
};
export type InstallSkillV1SkillsSkillIdInstallPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type InstallSkillV1SkillsSkillIdInstallPostError = InstallSkillV1SkillsSkillIdInstallPostErrors[keyof InstallSkillV1SkillsSkillIdInstallPostErrors];
export type InstallSkillV1SkillsSkillIdInstallPostResponses = {
    /**
     * Successful Response
     */
    200: SkillResponse;
};
export type InstallSkillV1SkillsSkillIdInstallPostResponse = InstallSkillV1SkillsSkillIdInstallPostResponses[keyof InstallSkillV1SkillsSkillIdInstallPostResponses];
export type ListSkillMembersV1SkillsSkillIdMembersGetData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}/members';
};
export type ListSkillMembersV1SkillsSkillIdMembersGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListSkillMembersV1SkillsSkillIdMembersGetError = ListSkillMembersV1SkillsSkillIdMembersGetErrors[keyof ListSkillMembersV1SkillsSkillIdMembersGetErrors];
export type ListSkillMembersV1SkillsSkillIdMembersGetResponses = {
    /**
     * Response List Skill Members V1 Skills  Skill Id  Members Get
     *
     * Successful Response
     */
    200: Array<SkillMemberResponse>;
};
export type ListSkillMembersV1SkillsSkillIdMembersGetResponse = ListSkillMembersV1SkillsSkillIdMembersGetResponses[keyof ListSkillMembersV1SkillsSkillIdMembersGetResponses];
export type AddSkillMemberV1SkillsSkillIdMembersPostData = {
    body: SkillMemberAddRequest;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}/members';
};
export type AddSkillMemberV1SkillsSkillIdMembersPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AddSkillMemberV1SkillsSkillIdMembersPostError = AddSkillMemberV1SkillsSkillIdMembersPostErrors[keyof AddSkillMemberV1SkillsSkillIdMembersPostErrors];
export type AddSkillMemberV1SkillsSkillIdMembersPostResponses = {
    /**
     * Successful Response
     */
    200: SkillMemberResponse;
};
export type AddSkillMemberV1SkillsSkillIdMembersPostResponse = AddSkillMemberV1SkillsSkillIdMembersPostResponses[keyof AddSkillMemberV1SkillsSkillIdMembersPostResponses];
export type RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteData = {
    body?: never;
    path: {
        /**
         * Skill Id
         */
        skill_id: string;
        /**
         * Child Skill Id
         */
        child_skill_id: string;
    };
    query?: never;
    url: '/v1/skills/{skill_id}/members/{child_skill_id}';
};
export type RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteError = RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteErrors[keyof RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteErrors];
export type RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetAllTasksV1TasksGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Status
         *
         * Filter by task status
         */
        status?: string | null;
        /**
         * Limit
         *
         * Maximum number of tasks to return
         */
        limit?: number;
        /**
         * Offset
         *
         * Number of tasks to skip
         */
        offset?: number;
    };
    url: '/v1/tasks/';
};
export type GetAllTasksV1TasksGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetAllTasksV1TasksGetError = GetAllTasksV1TasksGetErrors[keyof GetAllTasksV1TasksGetErrors];
export type GetAllTasksV1TasksGetResponses = {
    /**
     * Response Get All Tasks V1 Tasks  Get
     *
     * Successful Response
     */
    200: Array<TaskWithAgent>;
};
export type GetAllTasksV1TasksGetResponse = GetAllTasksV1TasksGetResponses[keyof GetAllTasksV1TasksGetResponses];
export type GetTaskByIdV1TasksTaskIdGetData = {
    body?: never;
    path: {
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/tasks/{task_id}';
};
export type GetTaskByIdV1TasksTaskIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetTaskByIdV1TasksTaskIdGetError = GetTaskByIdV1TasksTaskIdGetErrors[keyof GetTaskByIdV1TasksTaskIdGetErrors];
export type GetTaskByIdV1TasksTaskIdGetResponses = {
    /**
     * Successful Response
     */
    200: TaskWithAgent;
};
export type GetTaskByIdV1TasksTaskIdGetResponse = GetTaskByIdV1TasksTaskIdGetResponses[keyof GetTaskByIdV1TasksTaskIdGetResponses];
export type ContinueTaskExecutionV1TasksTaskIdContinuePostData = {
    body: ContinueTaskPayload;
    path: {
        /**
         * Task Id
         */
        task_id: string;
    };
    query?: never;
    url: '/v1/tasks/{task_id}/continue';
};
export type ContinueTaskExecutionV1TasksTaskIdContinuePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ContinueTaskExecutionV1TasksTaskIdContinuePostError = ContinueTaskExecutionV1TasksTaskIdContinuePostErrors[keyof ContinueTaskExecutionV1TasksTaskIdContinuePostErrors];
export type ContinueTaskExecutionV1TasksTaskIdContinuePostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type ListTriggersV1TriggersGetData = {
    body?: never;
    path?: never;
    query?: {
        /**
         * Agent Id
         *
         * Filter by agent ID
         */
        agent_id?: string | null;
        /**
         * Trigger Type
         *
         * Filter by trigger type (cron, webhook)
         */
        trigger_type?: string | null;
        /**
         * Active Only
         *
         * Only return active triggers
         */
        active_only?: boolean;
        /**
         * Limit
         *
         * Maximum number of triggers to return
         */
        limit?: number;
    };
    url: '/v1/triggers/';
};
export type ListTriggersV1TriggersGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListTriggersV1TriggersGetError = ListTriggersV1TriggersGetErrors[keyof ListTriggersV1TriggersGetErrors];
export type ListTriggersV1TriggersGetResponses = {
    /**
     * Response List Triggers V1 Triggers  Get
     *
     * Successful Response
     */
    200: Array<TriggerResponse>;
};
export type ListTriggersV1TriggersGetResponse = ListTriggersV1TriggersGetResponses[keyof ListTriggersV1TriggersGetResponses];
export type CreateTriggerV1TriggersPostData = {
    body: TriggerCreate;
    path?: never;
    query?: never;
    url: '/v1/triggers/';
};
export type CreateTriggerV1TriggersPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateTriggerV1TriggersPostError = CreateTriggerV1TriggersPostErrors[keyof CreateTriggerV1TriggersPostErrors];
export type CreateTriggerV1TriggersPostResponses = {
    /**
     * Successful Response
     */
    201: TriggerResponse;
};
export type CreateTriggerV1TriggersPostResponse = CreateTriggerV1TriggersPostResponses[keyof CreateTriggerV1TriggersPostResponses];
export type GetCatalogV1TriggersCatalogGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/triggers/catalog';
};
export type GetCatalogV1TriggersCatalogGetResponses = {
    /**
     * Response Get Catalog V1 Triggers Catalog Get
     *
     * Successful Response
     */
    200: Array<{
        [key: string]: unknown;
    }>;
};
export type GetCatalogV1TriggersCatalogGetResponse = GetCatalogV1TriggersCatalogGetResponses[keyof GetCatalogV1TriggersCatalogGetResponses];
export type GetChannelEventsV1TriggersChannelsEventsGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/triggers/channels/events';
};
export type GetChannelEventsV1TriggersChannelsEventsGetResponses = {
    /**
     * Response Get Channel Events V1 Triggers Channels Events Get
     *
     * Successful Response
     */
    200: {
        [key: string]: Array<string>;
    };
};
export type GetChannelEventsV1TriggersChannelsEventsGetResponse = GetChannelEventsV1TriggersChannelsEventsGetResponses[keyof GetChannelEventsV1TriggersChannelsEventsGetResponses];
export type TriggersHealthCheckV1TriggersHealthGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/triggers/health';
};
export type TriggersHealthCheckV1TriggersHealthGetResponses = {
    /**
     * Response Triggers Health Check V1 Triggers Health Get
     *
     * Successful Response
     */
    200: {
        [key: string]: unknown;
    };
};
export type TriggersHealthCheckV1TriggersHealthGetResponse = TriggersHealthCheckV1TriggersHealthGetResponses[keyof TriggersHealthCheckV1TriggersHealthGetResponses];
export type DeleteTriggerV1TriggersTriggerIdDeleteData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: never;
    url: '/v1/triggers/{trigger_id}';
};
export type DeleteTriggerV1TriggersTriggerIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DeleteTriggerV1TriggersTriggerIdDeleteError = DeleteTriggerV1TriggersTriggerIdDeleteErrors[keyof DeleteTriggerV1TriggersTriggerIdDeleteErrors];
export type DeleteTriggerV1TriggersTriggerIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type DeleteTriggerV1TriggersTriggerIdDeleteResponse = DeleteTriggerV1TriggersTriggerIdDeleteResponses[keyof DeleteTriggerV1TriggersTriggerIdDeleteResponses];
export type GetTriggerV1TriggersTriggerIdGetData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: never;
    url: '/v1/triggers/{trigger_id}';
};
export type GetTriggerV1TriggersTriggerIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetTriggerV1TriggersTriggerIdGetError = GetTriggerV1TriggersTriggerIdGetErrors[keyof GetTriggerV1TriggersTriggerIdGetErrors];
export type GetTriggerV1TriggersTriggerIdGetResponses = {
    /**
     * Successful Response
     */
    200: TriggerResponse;
};
export type GetTriggerV1TriggersTriggerIdGetResponse = GetTriggerV1TriggersTriggerIdGetResponses[keyof GetTriggerV1TriggersTriggerIdGetResponses];
export type UpdateTriggerV1TriggersTriggerIdPutData = {
    body: TriggerUpdate;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: never;
    url: '/v1/triggers/{trigger_id}';
};
export type UpdateTriggerV1TriggersTriggerIdPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateTriggerV1TriggersTriggerIdPutError = UpdateTriggerV1TriggersTriggerIdPutErrors[keyof UpdateTriggerV1TriggersTriggerIdPutErrors];
export type UpdateTriggerV1TriggersTriggerIdPutResponses = {
    /**
     * Successful Response
     */
    200: TriggerResponse;
};
export type UpdateTriggerV1TriggersTriggerIdPutResponse = UpdateTriggerV1TriggersTriggerIdPutResponses[keyof UpdateTriggerV1TriggersTriggerIdPutResponses];
export type GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: {
        /**
         * Page
         *
         * Page number
         */
        page?: number;
        /**
         * Page Size
         *
         * Number of executions per page
         */
        page_size?: number;
    };
    url: '/v1/triggers/{trigger_id}/correlations';
};
export type GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetError = GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetErrors[keyof GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetErrors];
export type GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetResponses = {
    /**
     * Successful Response
     */
    200: ExecutionCorrelationResponse;
};
export type GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetResponse = GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetResponses[keyof GetExecutionCorrelationsV1TriggersTriggerIdCorrelationsGetResponses];
export type DisableTriggerV1TriggersTriggerIdDisablePostData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: never;
    url: '/v1/triggers/{trigger_id}/disable';
};
export type DisableTriggerV1TriggersTriggerIdDisablePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type DisableTriggerV1TriggersTriggerIdDisablePostError = DisableTriggerV1TriggersTriggerIdDisablePostErrors[keyof DisableTriggerV1TriggersTriggerIdDisablePostErrors];
export type DisableTriggerV1TriggersTriggerIdDisablePostResponses = {
    /**
     * Response Disable Trigger V1 Triggers  Trigger Id  Disable Post
     *
     * Successful Response
     */
    200: {
        [key: string]: unknown;
    };
};
export type DisableTriggerV1TriggersTriggerIdDisablePostResponse = DisableTriggerV1TriggersTriggerIdDisablePostResponses[keyof DisableTriggerV1TriggersTriggerIdDisablePostResponses];
export type EnableTriggerV1TriggersTriggerIdEnablePostData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: never;
    url: '/v1/triggers/{trigger_id}/enable';
};
export type EnableTriggerV1TriggersTriggerIdEnablePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type EnableTriggerV1TriggersTriggerIdEnablePostError = EnableTriggerV1TriggersTriggerIdEnablePostErrors[keyof EnableTriggerV1TriggersTriggerIdEnablePostErrors];
export type EnableTriggerV1TriggersTriggerIdEnablePostResponses = {
    /**
     * Response Enable Trigger V1 Triggers  Trigger Id  Enable Post
     *
     * Successful Response
     */
    200: {
        [key: string]: unknown;
    };
};
export type EnableTriggerV1TriggersTriggerIdEnablePostResponse = EnableTriggerV1TriggersTriggerIdEnablePostResponses[keyof EnableTriggerV1TriggersTriggerIdEnablePostResponses];
export type ExecuteTriggerV1TriggersTriggerIdExecutePostData = {
    body: TriggerExecuteRequest;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: never;
    url: '/v1/triggers/{trigger_id}/execute';
};
export type ExecuteTriggerV1TriggersTriggerIdExecutePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ExecuteTriggerV1TriggersTriggerIdExecutePostError = ExecuteTriggerV1TriggersTriggerIdExecutePostErrors[keyof ExecuteTriggerV1TriggersTriggerIdExecutePostErrors];
export type ExecuteTriggerV1TriggersTriggerIdExecutePostResponses = {
    /**
     * Response Execute Trigger V1 Triggers  Trigger Id  Execute Post
     *
     * Successful Response
     */
    200: {
        [key: string]: unknown;
    };
};
export type ExecuteTriggerV1TriggersTriggerIdExecutePostResponse = ExecuteTriggerV1TriggersTriggerIdExecutePostResponses[keyof ExecuteTriggerV1TriggersTriggerIdExecutePostResponses];
export type GetExecutionHistoryV1TriggersTriggerIdExecutionsGetData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: {
        /**
         * Page
         *
         * Page number
         */
        page?: number;
        /**
         * Page Size
         *
         * Number of executions per page
         */
        page_size?: number;
        /**
         * Status
         *
         * Filter by execution status (success, failed, timeout)
         */
        status?: string | null;
        /**
         * Start Time
         *
         * Filter executions after this time
         */
        start_time?: string | null;
        /**
         * End Time
         *
         * Filter executions before this time
         */
        end_time?: string | null;
    };
    url: '/v1/triggers/{trigger_id}/executions';
};
export type GetExecutionHistoryV1TriggersTriggerIdExecutionsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetExecutionHistoryV1TriggersTriggerIdExecutionsGetError = GetExecutionHistoryV1TriggersTriggerIdExecutionsGetErrors[keyof GetExecutionHistoryV1TriggersTriggerIdExecutionsGetErrors];
export type GetExecutionHistoryV1TriggersTriggerIdExecutionsGetResponses = {
    /**
     * Successful Response
     */
    200: ExecutionHistoryResponse;
};
export type GetExecutionHistoryV1TriggersTriggerIdExecutionsGetResponse = GetExecutionHistoryV1TriggersTriggerIdExecutionsGetResponses[keyof GetExecutionHistoryV1TriggersTriggerIdExecutionsGetResponses];
export type GetExecutionMetricsV1TriggersTriggerIdMetricsGetData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: {
        /**
         * Hours
         *
         * Time period in hours (max 7 days)
         */
        hours?: number;
    };
    url: '/v1/triggers/{trigger_id}/metrics';
};
export type GetExecutionMetricsV1TriggersTriggerIdMetricsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetExecutionMetricsV1TriggersTriggerIdMetricsGetError = GetExecutionMetricsV1TriggersTriggerIdMetricsGetErrors[keyof GetExecutionMetricsV1TriggersTriggerIdMetricsGetErrors];
export type GetExecutionMetricsV1TriggersTriggerIdMetricsGetResponses = {
    /**
     * Successful Response
     */
    200: ExecutionMetricsResponse;
};
export type GetExecutionMetricsV1TriggersTriggerIdMetricsGetResponse = GetExecutionMetricsV1TriggersTriggerIdMetricsGetResponses[keyof GetExecutionMetricsV1TriggersTriggerIdMetricsGetResponses];
export type GetTriggerStatusV1TriggersTriggerIdStatusGetData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: never;
    url: '/v1/triggers/{trigger_id}/status';
};
export type GetTriggerStatusV1TriggersTriggerIdStatusGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetTriggerStatusV1TriggersTriggerIdStatusGetError = GetTriggerStatusV1TriggersTriggerIdStatusGetErrors[keyof GetTriggerStatusV1TriggersTriggerIdStatusGetErrors];
export type GetTriggerStatusV1TriggersTriggerIdStatusGetResponses = {
    /**
     * Successful Response
     */
    200: TriggerStatusResponse;
};
export type GetTriggerStatusV1TriggersTriggerIdStatusGetResponse = GetTriggerStatusV1TriggersTriggerIdStatusGetResponses[keyof GetTriggerStatusV1TriggersTriggerIdStatusGetResponses];
export type GetExecutionTimelineV1TriggersTriggerIdTimelineGetData = {
    body?: never;
    path: {
        /**
         * Trigger Id
         */
        trigger_id: string;
    };
    query?: {
        /**
         * Hours
         *
         * Time period in hours (max 7 days)
         */
        hours?: number;
        /**
         * Bucket Size Minutes
         *
         * Time bucket size in minutes
         */
        bucket_size_minutes?: number;
    };
    url: '/v1/triggers/{trigger_id}/timeline';
};
export type GetExecutionTimelineV1TriggersTriggerIdTimelineGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetExecutionTimelineV1TriggersTriggerIdTimelineGetError = GetExecutionTimelineV1TriggersTriggerIdTimelineGetErrors[keyof GetExecutionTimelineV1TriggersTriggerIdTimelineGetErrors];
export type GetExecutionTimelineV1TriggersTriggerIdTimelineGetResponses = {
    /**
     * Successful Response
     */
    200: ExecutionTimelineResponse;
};
export type GetExecutionTimelineV1TriggersTriggerIdTimelineGetResponse = GetExecutionTimelineV1TriggersTriggerIdTimelineGetResponses[keyof GetExecutionTimelineV1TriggersTriggerIdTimelineGetResponses];
export type GetDashboardV1WorkspaceDashboardGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/workspace/dashboard';
};
export type GetDashboardV1WorkspaceDashboardGetResponses = {
    /**
     * Successful Response
     */
    200: DashboardResponse;
};
export type GetDashboardV1WorkspaceDashboardGetResponse = GetDashboardV1WorkspaceDashboardGetResponses[keyof GetDashboardV1WorkspaceDashboardGetResponses];
export type ExportWorkspaceConfigV1WorkspaceExportGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/workspace/export';
};
export type ExportWorkspaceConfigV1WorkspaceExportGetResponses = {
    /**
     * Successful Response
     */
    200: string;
};
export type ExportWorkspaceConfigV1WorkspaceExportGetResponse = ExportWorkspaceConfigV1WorkspaceExportGetResponses[keyof ExportWorkspaceConfigV1WorkspaceExportGetResponses];
export type ImportWorkspaceConfigV1WorkspaceImportPostData = {
    body: ImportRequest;
    path?: never;
    query?: never;
    url: '/v1/workspace/import';
};
export type ImportWorkspaceConfigV1WorkspaceImportPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ImportWorkspaceConfigV1WorkspaceImportPostError = ImportWorkspaceConfigV1WorkspaceImportPostErrors[keyof ImportWorkspaceConfigV1WorkspaceImportPostErrors];
export type ImportWorkspaceConfigV1WorkspaceImportPostResponses = {
    /**
     * Successful Response
     */
    200: ImportResult;
};
export type ImportWorkspaceConfigV1WorkspaceImportPostResponse = ImportWorkspaceConfigV1WorkspaceImportPostResponses[keyof ImportWorkspaceConfigV1WorkspaceImportPostResponses];
export type ImportWorkspaceConfigFileV1WorkspaceImportFilePostData = {
    body: BodyImportWorkspaceConfigFileV1WorkspaceImportFilePost;
    path?: never;
    query?: {
        /**
         * Skip Missing Dependencies
         *
         * Skip resources with missing dependencies
         */
        skip_missing_dependencies?: boolean;
        /**
         * Override Existing
         *
         * Override existing resources with same name
         */
        override_existing?: boolean;
    };
    url: '/v1/workspace/import/file';
};
export type ImportWorkspaceConfigFileV1WorkspaceImportFilePostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ImportWorkspaceConfigFileV1WorkspaceImportFilePostError = ImportWorkspaceConfigFileV1WorkspaceImportFilePostErrors[keyof ImportWorkspaceConfigFileV1WorkspaceImportFilePostErrors];
export type ImportWorkspaceConfigFileV1WorkspaceImportFilePostResponses = {
    /**
     * Successful Response
     */
    200: ImportResult;
};
export type ImportWorkspaceConfigFileV1WorkspaceImportFilePostResponse = ImportWorkspaceConfigFileV1WorkspaceImportFilePostResponses[keyof ImportWorkspaceConfigFileV1WorkspaceImportFilePostResponses];
export type GetWorkspaceSettingsV1WorkspaceSettingsGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/workspace/settings';
};
export type GetWorkspaceSettingsV1WorkspaceSettingsGetResponses = {
    /**
     * Successful Response
     */
    200: WorkspaceSettingsResponse;
};
export type GetWorkspaceSettingsV1WorkspaceSettingsGetResponse = GetWorkspaceSettingsV1WorkspaceSettingsGetResponses[keyof GetWorkspaceSettingsV1WorkspaceSettingsGetResponses];
export type UpdateWorkspaceSettingsV1WorkspaceSettingsPutData = {
    body: WorkspaceSettingsUpdate;
    path?: never;
    query?: never;
    url: '/v1/workspace/settings';
};
export type UpdateWorkspaceSettingsV1WorkspaceSettingsPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type UpdateWorkspaceSettingsV1WorkspaceSettingsPutError = UpdateWorkspaceSettingsV1WorkspaceSettingsPutErrors[keyof UpdateWorkspaceSettingsV1WorkspaceSettingsPutErrors];
export type UpdateWorkspaceSettingsV1WorkspaceSettingsPutResponses = {
    /**
     * Successful Response
     */
    200: WorkspaceSettingsResponse;
};
export type UpdateWorkspaceSettingsV1WorkspaceSettingsPutResponse = UpdateWorkspaceSettingsV1WorkspaceSettingsPutResponses[keyof UpdateWorkspaceSettingsV1WorkspaceSettingsPutResponses];
export type ListWorkspacesV1WorkspacesGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/v1/workspaces';
};
export type ListWorkspacesV1WorkspacesGetResponses = {
    /**
     * Response List Workspaces V1 Workspaces Get
     *
     * Successful Response
     */
    200: Array<WorkspaceResponse>;
};
export type ListWorkspacesV1WorkspacesGetResponse = ListWorkspacesV1WorkspacesGetResponses[keyof ListWorkspacesV1WorkspacesGetResponses];
export type CreateWorkspaceV1WorkspacesPostData = {
    body: CreateWorkspaceBody;
    path?: never;
    query?: never;
    url: '/v1/workspaces';
};
export type CreateWorkspaceV1WorkspacesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateWorkspaceV1WorkspacesPostError = CreateWorkspaceV1WorkspacesPostErrors[keyof CreateWorkspaceV1WorkspacesPostErrors];
export type CreateWorkspaceV1WorkspacesPostResponses = {
    /**
     * Successful Response
     */
    201: WorkspaceResponse;
};
export type CreateWorkspaceV1WorkspacesPostResponse = CreateWorkspaceV1WorkspacesPostResponses[keyof CreateWorkspaceV1WorkspacesPostResponses];
export type ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetData = {
    body?: never;
    path: {
        /**
         * Workspace Id
         */
        workspace_id: string;
    };
    query?: never;
    url: '/v1/workspaces/{workspace_id}/invitations';
};
export type ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetError = ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetErrors[keyof ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetErrors];
export type ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetResponses = {
    /**
     * Response List Invitations V1 Workspaces  Workspace Id  Invitations Get
     *
     * Successful Response
     */
    200: Array<InvitationResponse>;
};
export type ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetResponse = ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetResponses[keyof ListInvitationsV1WorkspacesWorkspaceIdInvitationsGetResponses];
export type CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostData = {
    body: CreateInvitationBody;
    path: {
        /**
         * Workspace Id
         */
        workspace_id: string;
    };
    query?: never;
    url: '/v1/workspaces/{workspace_id}/invitations';
};
export type CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostError = CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostErrors[keyof CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostErrors];
export type CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostResponses = {
    /**
     * Successful Response
     */
    201: InvitationCreatedResponse;
};
export type CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostResponse = CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostResponses[keyof CreateInvitationV1WorkspacesWorkspaceIdInvitationsPostResponses];
export type RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteData = {
    body?: never;
    path: {
        /**
         * Workspace Id
         */
        workspace_id: string;
        /**
         * Invitation Id
         */
        invitation_id: string;
    };
    query?: never;
    url: '/v1/workspaces/{workspace_id}/invitations/{invitation_id}';
};
export type RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteError = RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteErrors[keyof RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteErrors];
export type RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteResponse = RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteResponses[keyof RevokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDeleteResponses];
export type ListMembersV1WorkspacesWorkspaceIdMembersGetData = {
    body?: never;
    path: {
        /**
         * Workspace Id
         */
        workspace_id: string;
    };
    query?: never;
    url: '/v1/workspaces/{workspace_id}/members';
};
export type ListMembersV1WorkspacesWorkspaceIdMembersGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListMembersV1WorkspacesWorkspaceIdMembersGetError = ListMembersV1WorkspacesWorkspaceIdMembersGetErrors[keyof ListMembersV1WorkspacesWorkspaceIdMembersGetErrors];
export type ListMembersV1WorkspacesWorkspaceIdMembersGetResponses = {
    /**
     * Response List Members V1 Workspaces  Workspace Id  Members Get
     *
     * Successful Response
     */
    200: Array<MemberResponse>;
};
export type ListMembersV1WorkspacesWorkspaceIdMembersGetResponse = ListMembersV1WorkspacesWorkspaceIdMembersGetResponses[keyof ListMembersV1WorkspacesWorkspaceIdMembersGetResponses];
export type RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteData = {
    body?: never;
    path: {
        /**
         * Workspace Id
         */
        workspace_id: string;
        /**
         * User Id
         */
        user_id: string;
    };
    query?: never;
    url: '/v1/workspaces/{workspace_id}/members/{user_id}';
};
export type RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteError = RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteErrors[keyof RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteErrors];
export type RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteResponses = {
    /**
     * Successful Response
     */
    204: void;
};
export type RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteResponse = RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteResponses[keyof RemoveMemberV1WorkspacesWorkspaceIdMembersUserIdDeleteResponses];
export type WebhookHealthCheckWebhooksHealthGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/webhooks/health';
};
export type WebhookHealthCheckWebhooksHealthGetResponses = {
    /**
     * Response Webhook Health Check Webhooks Health Get
     *
     * Successful Response
     */
    200: {
        [key: string]: unknown;
    };
};
export type WebhookHealthCheckWebhooksHealthGetResponse = WebhookHealthCheckWebhooksHealthGetResponses[keyof WebhookHealthCheckWebhooksHealthGetResponses];
export type HandleWebhookWebhooksWebhookIdDeleteData = {
    body?: never;
    path: {
        /**
         * Webhook Id
         */
        webhook_id: string;
    };
    query?: never;
    url: '/webhooks/{webhook_id}';
};
export type HandleWebhookWebhooksWebhookIdDeleteErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HandleWebhookWebhooksWebhookIdDeleteError = HandleWebhookWebhooksWebhookIdDeleteErrors[keyof HandleWebhookWebhooksWebhookIdDeleteErrors];
export type HandleWebhookWebhooksWebhookIdDeleteResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HandleWebhookWebhooksWebhookIdGetData = {
    body?: never;
    path: {
        /**
         * Webhook Id
         */
        webhook_id: string;
    };
    query?: never;
    url: '/webhooks/{webhook_id}';
};
export type HandleWebhookWebhooksWebhookIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HandleWebhookWebhooksWebhookIdGetError = HandleWebhookWebhooksWebhookIdGetErrors[keyof HandleWebhookWebhooksWebhookIdGetErrors];
export type HandleWebhookWebhooksWebhookIdGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HandleWebhookWebhooksWebhookIdHeadData = {
    body?: never;
    path: {
        /**
         * Webhook Id
         */
        webhook_id: string;
    };
    query?: never;
    url: '/webhooks/{webhook_id}';
};
export type HandleWebhookWebhooksWebhookIdHeadErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HandleWebhookWebhooksWebhookIdHeadError = HandleWebhookWebhooksWebhookIdHeadErrors[keyof HandleWebhookWebhooksWebhookIdHeadErrors];
export type HandleWebhookWebhooksWebhookIdHeadResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HandleWebhookWebhooksWebhookIdOptionsData = {
    body?: never;
    path: {
        /**
         * Webhook Id
         */
        webhook_id: string;
    };
    query?: never;
    url: '/webhooks/{webhook_id}';
};
export type HandleWebhookWebhooksWebhookIdOptionsErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HandleWebhookWebhooksWebhookIdOptionsError = HandleWebhookWebhooksWebhookIdOptionsErrors[keyof HandleWebhookWebhooksWebhookIdOptionsErrors];
export type HandleWebhookWebhooksWebhookIdOptionsResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HandleWebhookWebhooksWebhookIdPatchData = {
    body?: never;
    path: {
        /**
         * Webhook Id
         */
        webhook_id: string;
    };
    query?: never;
    url: '/webhooks/{webhook_id}';
};
export type HandleWebhookWebhooksWebhookIdPatchErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HandleWebhookWebhooksWebhookIdPatchError = HandleWebhookWebhooksWebhookIdPatchErrors[keyof HandleWebhookWebhooksWebhookIdPatchErrors];
export type HandleWebhookWebhooksWebhookIdPatchResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HandleWebhookWebhooksWebhookIdPostData = {
    body?: never;
    path: {
        /**
         * Webhook Id
         */
        webhook_id: string;
    };
    query?: never;
    url: '/webhooks/{webhook_id}';
};
export type HandleWebhookWebhooksWebhookIdPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HandleWebhookWebhooksWebhookIdPostError = HandleWebhookWebhooksWebhookIdPostErrors[keyof HandleWebhookWebhooksWebhookIdPostErrors];
export type HandleWebhookWebhooksWebhookIdPostResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type HandleWebhookWebhooksWebhookIdPutData = {
    body?: never;
    path: {
        /**
         * Webhook Id
         */
        webhook_id: string;
    };
    query?: never;
    url: '/webhooks/{webhook_id}';
};
export type HandleWebhookWebhooksWebhookIdPutErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type HandleWebhookWebhooksWebhookIdPutError = HandleWebhookWebhooksWebhookIdPutErrors[keyof HandleWebhookWebhooksWebhookIdPutErrors];
export type HandleWebhookWebhooksWebhookIdPutResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
