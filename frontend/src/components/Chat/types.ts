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

// System Message (for workflow events, debugging, etc.)
export interface SystemData extends BaseMessageData {
  message: string;
  level?: "info" | "warning" | "error";
}

// Export all message component types
export type MessageComponentType =
  | { type: "llm_response"; data: LLMResponseData }
  | { type: "llm_chunk"; data: LLMChunkData }
  | { type: "tool_call_started"; data: ToolCallStartedData }
  | { type: "tool_result"; data: ToolResultData }
  | { type: "error"; data: ErrorData }
  | { type: "workflow_result"; data: WorkflowResultData }
  | { type: "system"; data: SystemData };
