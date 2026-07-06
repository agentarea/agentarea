// Base message data structure
export interface BaseMessageData {
  id: string;
  timestamp: string;
  agent_id: string;
  event_type: string;
}

// LLM Response Message
export interface LLMResponseData extends BaseMessageData {
  content: string;
  thinking?: string;
  role?: string;
  tool_calls?: Array<{
    function: {
      name: string;
      arguments: string;
    };
    id: string;
    type: string;
  }>;
  usage?: {
    cost: number;
    usage: {
      completion_tokens: number;
      prompt_tokens: number;
      total_tokens: number;
    };
  };
}

// Tool Call Started Message
export interface ToolCallStartedData extends BaseMessageData {
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, unknown>;
  /** MCP server that owns this tool (absent for built-in/sandbox tools). */
  server_name?: string;
  server_icon?: string;
}

// Tool Result Message
export interface ToolResultData extends BaseMessageData {
  tool_name: string;
  tool_call_id: string;
  result: unknown;
  success: boolean;
  execution_time?: string;
  arguments?: Record<string, unknown>;
  /** MCP server that owns this tool (absent for built-in/sandbox tools). */
  server_name?: string;
  server_icon?: string;
}

// LLM Chunk Message (for streaming)
export interface LLMChunkData extends BaseMessageData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
  chunk_type?: "text" | "thinking";
  thinking?: string;
}

// Error Message (Enhanced)
export interface ErrorData extends BaseMessageData {
  error: string;
  error_type?: string;
  raw_error?: string;
  is_auth_error?: boolean;
  is_rate_limit_error?: boolean;
  is_quota_error?: boolean;
  is_model_error?: boolean;
  is_network_error?: boolean;
  retryable?: boolean;
  tool_name?: string;
  arguments?: Record<string, unknown>;
}

// Workflow Result Message
export interface WorkflowResultData extends BaseMessageData {
  result?: string;
  final_response?: string;
  success: boolean;
  iterations_completed?: number;
  total_cost?: number | string;
}

// A2UI v0.9 — 18 primitive component types from the basic catalog
export type A2UIComponentType =
  // Display
  | "Text"
  | "Image"
  | "Icon"
  | "Video"
  | "AudioPlayer"
  | "Divider"
  // Layout
  | "Row"
  | "Column"
  | "List"
  // Container
  | "Card"
  | "Tabs"
  | "Modal"
  // Interactive
  | "Button"
  | "TextField"
  | "CheckBox"
  | "ChoicePicker"
  | "Slider"
  | "DateTimeInput";

// DynamicString: literal value or JSON Pointer data binding
export type DynamicString = string | { path: string };
export type DynamicNumber = number | { path: string };
export type DynamicBoolean = boolean | { path: string };
export type DynamicStringList = string[] | { path: string };

// A2UI Action (what happens when a user interacts)
export interface A2UIAction {
  event?: { name: string; context?: Record<string, DynamicString> };
  functionCall?: { call: string; args?: Record<string, unknown> };
}

// Flat adjacency-list component node (children are ID strings, not nested objects)
export interface A2UIComponent {
  id: string;
  component: A2UIComponentType;
  // Layout children (Row, Column, List)
  children?: string[];
  // Single child (Card, Modal trigger/content, Button)
  child?: string;
  // Common props
  accessibility?: { label?: string; description?: string };
  weight?: number;
  action?: A2UIAction;
  align?: string;
  alt?: DynamicString;
  axis?: "horizontal" | "vertical";
  content?: string;
  description?: DynamicString;
  direction?: "horizontal" | "vertical";
  disabled?: boolean;
  displayStyle?: string;
  enableDate?: boolean;
  enableTime?: boolean;
  fit?: "contain" | "cover" | "fill" | "none" | "scale-down";
  justify?: string;
  label?: DynamicString;
  max?: DynamicString | DynamicNumber;
  min?: DynamicString | DynamicNumber;
  name?: DynamicString;
  options?: Array<{ label: string; value: string }>;
  placeholder?: DynamicString;
  tabs?: Array<{ title: string; child: string }>;
  text?: DynamicString;
  trigger?: string;
  url?: DynamicString;
  value?: DynamicString | DynamicNumber | DynamicBoolean;
  variant?: string;
  // Per-component props (open-ended to support all catalog props)
  [key: string]: unknown;
}

// A2UI surface state — accumulated from lifecycle events
export interface A2UISurface {
  surfaceId: string;
  catalogId: string;
  theme?: Record<string, unknown>;
  sendDataModel?: boolean;
  /** Flat map of component id → component node */
  components: Record<string, A2UIComponent>;
  /** JSON data model for data bindings */
  dataModel: Record<string, unknown>;
}

// The chat message type for a live A2UI surface
export interface A2UISurfaceData extends BaseMessageData {
  surfaceId: string;
  surface: A2UISurface;
}

// System Message (for workflow events, debugging, etc.)
export interface SystemData extends BaseMessageData {
  message: string;
  level?: "info" | "warning" | "error";
}

// Approval Request Message
export interface ApprovalRequestData extends BaseMessageData {
  escalation_id: string;
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, unknown>;
  message: string;
  resolved?: boolean;
  approved?: boolean;
  deny_comment?: string;
  _onResolve?: (
    escalationId: string,
    approved: boolean,
    comment: string
  ) => void;
}

// User message from follow-up (MessageQueued event)
export interface UserMessageData extends BaseMessageData {
  content: string;
}

// A single field in a structured user-input request (request_user_input tool)
export type HumanInputFieldType =
  | "text"
  | "textarea"
  | "select"
  | "multiselect"
  | "boolean"
  | "number"
  | "secret";

export interface HumanInputField {
  id: string;
  question: string;
  type: HumanInputFieldType;
  required?: boolean;
  options?: string[];
  /** Suggested workspace secret name for `secret` fields. */
  secret_name?: string;
}

// Secret values are routed to the vault at the API boundary; the agent only ever
// receives a `secret_ref`, never the raw value.
export interface HumanInputSecretValue {
  value: string;
  secret_name?: string;
}

// Structured user-input request message (paired update event: HumanInputReceived)
export interface HumanInputRequestData extends BaseMessageData {
  input_request_id: string;
  tool_call_id?: string;
  question: string;
  questions: HumanInputField[];
  allow_custom_response?: boolean;
  input_mode?: string;
  resolved?: boolean;
  _onSubmit?: (
    inputRequestId: string,
    answers: Record<string, unknown>,
    secrets: Record<string, HumanInputSecretValue>
  ) => void;
}

// Tool Call Group Message (groups consecutive tool calls/results into one block)
export interface ToolCallGroupData extends BaseMessageData {
  tools: Array<{
    tool_name: string;
    tool_call_id: string;
    result: unknown;
    success: boolean;
    arguments?: Record<string, unknown>;
    execution_time?: string;
    pending?: boolean; // true if still in "calling..." state
    server_name?: string;
    server_icon?: string;
  }>;
}

// Export all message component types
export type MessageComponentType =
  | { type: "llm_response"; data: LLMResponseData }
  | { type: "llm_chunk"; data: LLMChunkData }
  | { type: "tool_call_started"; data: ToolCallStartedData }
  | { type: "tool_result"; data: ToolResultData }
  | { type: "tool_call_group"; data: ToolCallGroupData }
  | { type: "error"; data: ErrorData }
  | { type: "workflow_result"; data: WorkflowResultData }
  | { type: "system"; data: SystemData }
  | { type: "a2ui_surface"; data: A2UISurfaceData }
  | { type: "approval_request"; data: ApprovalRequestData }
  | { type: "input_request"; data: HumanInputRequestData }
  | { type: "user_message"; data: UserMessageData };

// Chat Message Types
export interface UserChatMessage {
  id: string;
  content: string;
  role: "user";
  timestamp: string;
  files?: File[];
}

export interface WelcomeMessage {
  id: string;
  content: string;
  role: "assistant";
  timestamp: string;
  agent_id: string;
}

// Unified Chat Message Type
export type ChatMessage =
  | UserChatMessage
  | WelcomeMessage
  | MessageComponentType;

// Raw SSE event payload shape — covers all event types parsed in EventParser.ts.
// Uses an open index signature so it accepts any backend-emitted event without `any`.
export interface SseEventData {
  task_id?: string;
  aggregate_id?: string;
  timestamp?: string;
  agent_id?: string;
  original_data?: SseEventData;
  content?: string;
  thinking?: string;
  role?: string;
  tool_calls?: unknown;
  usage?: unknown;
  chunk?: string;
  chunk_index?: number;
  is_final?: boolean;
  chunk_type?: string;
  error?: string;
  error_type?: string;
  model_id?: string;
  provider_type?: string;
  is_auth_error?: boolean;
  is_rate_limit_error?: boolean;
  retry_after?: string | number;
  is_quota_error?: boolean;
  quota_type?: string;
  is_model_error?: boolean;
  is_network_error?: boolean;
  status_code?: string | number;
  retryable?: boolean;
  tool_name?: string;
  tool_call_id?: string;
  arguments?: Record<string, unknown>;
  server_name?: string;
  server_icon?: string;
  result?: unknown;
  success?: boolean;
  execution_time?: string;
  final_response?: string;
  iterations_completed?: number;
  total_cost?: string | number;
  message?: string;
  goal_description?: string;
  usage_percentage?: number;
  cost?: string | number;
  limit?: string | number;
  surface_id?: string;
  catalog_id?: string;
  theme?: Record<string, unknown>;
  send_data_model?: boolean;
  escalation_id?: string;
  resolved?: boolean;
  approved?: boolean;
  deny_comment?: string;
  input_request_id?: string;
  question?: string;
  questions?: unknown[];
  allow_custom_response?: boolean;
  input_mode?: string;
  [key: string]: unknown;
}
