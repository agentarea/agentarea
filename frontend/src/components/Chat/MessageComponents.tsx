import React from 'react';
import { MessageWrapper } from './MessageWrapper';
import LLMResponseMessage from './componets/LLMResponseMessage';
import LLMChunkMessage from './componets/LLMChunkMessage';
import ToolCallStartedMessage from './componets/ToolCallStartedMessage';
import ToolResultMessage from './componets/ToolResultMessage';
import ErrorMessage from './componets/ErrorMessage';
import WorkflowResultMessage from './componets/WorkflowResultMessage';
import SystemMessage from './componets/SystemMessage';

// Base message data structure
interface BaseMessageData {
  id: string;
  timestamp: string;
  agent_id: string;
  event_type: string;
}

// LLM Response Message
interface LLMResponseData extends BaseMessageData {
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
interface ToolCallStartedData extends BaseMessageData {
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
}

// Tool Result Message
interface ToolResultData extends BaseMessageData {
  tool_name: string;
  result: any;
  success: boolean;
  execution_time?: string;
  arguments?: Record<string, any>;
}

// LLM Chunk Message (for streaming)
interface LLMChunkData extends BaseMessageData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
}

// Error Message (Enhanced)
interface ErrorData extends BaseMessageData {
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
interface WorkflowResultData extends BaseMessageData {
  result?: string;
  final_response?: string;
  success: boolean;
  iterations_completed?: number;
  total_cost?: number;
}

// System Message (for workflow events, debugging, etc.)
interface SystemData extends BaseMessageData {
  message: string;
  level?: 'info' | 'warning' | 'error';
}

// Export all message component types
export type MessageComponentType = 
  | { type: 'llm_response'; data: LLMResponseData }
  | { type: 'llm_chunk'; data: LLMChunkData }
  | { type: 'tool_call_started'; data: ToolCallStartedData }
  | { type: 'tool_result'; data: ToolResultData }
  | { type: 'error'; data: ErrorData }
  | { type: 'workflow_result'; data: WorkflowResultData }
  | { type: 'system'; data: SystemData };

// Message renderer that picks the right component
export const MessageRenderer: React.FC<{ message: MessageComponentType }> = ({ message }) => {
  switch (message.type) {
    case 'llm_response':
      return <LLMResponseMessage data={message.data} />;
    case 'llm_chunk':
      return <LLMChunkMessage data={message.data} />;
    case 'tool_call_started':
      return <ToolCallStartedMessage data={message.data} />;
    case 'tool_result':
      return <ToolResultMessage data={message.data} />;
    case 'error':
      return <ErrorMessage data={message.data} />;
    case 'workflow_result':
      return <WorkflowResultMessage data={message.data} />;
    case 'system':
      return <SystemMessage data={message.data} />;
    default:
      return null;
  }
};