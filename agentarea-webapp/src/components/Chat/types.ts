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
  arguments: Record<string, any>;
}

// Tool Result Message
export interface ToolResultData extends BaseMessageData {
  tool_name: string;
  tool_call_id: string;
  result: any;
  success: boolean;
  execution_time?: string;
  arguments?: Record<string, any>;
}

// LLM Chunk Message (for streaming)
export interface LLMChunkData extends BaseMessageData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
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
  arguments?: Record<string, any>;
}

// Workflow Result Message
export interface WorkflowResultData extends BaseMessageData {
  result?: string;
  final_response?: string;
  success: boolean;
  iterations_completed?: number;
  total_cost?: number;
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
  functionCall?: { call: string; args?: Record<string, any> };
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
  // Per-component props (open-ended to support all catalog props)
  [key: string]: any;
}

// A2UI surface state — accumulated from lifecycle events
export interface A2UISurface {
  surfaceId: string;
  catalogId: string;
  theme?: Record<string, any>;
  sendDataModel?: boolean;
  /** Flat map of component id → component node */
  components: Record<string, A2UIComponent>;
  /** JSON data model for data bindings */
  dataModel: Record<string, any>;
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
  arguments: Record<string, any>;
  message: string;
  resolved?: boolean;
  approved?: boolean;
  deny_comment?: string;
  _onResolve?: (escalationId: string, approved: boolean, comment: string) => void;
}

// Export all message component types
export type MessageComponentType =
  | { type: "llm_response"; data: LLMResponseData }
  | { type: "llm_chunk"; data: LLMChunkData }
  | { type: "tool_call_started"; data: ToolCallStartedData }
  | { type: "tool_result"; data: ToolResultData }
  | { type: "error"; data: ErrorData }
  | { type: "workflow_result"; data: WorkflowResultData }
  | { type: "system"; data: SystemData }
  | { type: "a2ui_surface"; data: A2UISurfaceData }
  | { type: "approval_request"; data: ApprovalRequestData };

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
export type ChatMessage = UserChatMessage | WelcomeMessage | MessageComponentType;
