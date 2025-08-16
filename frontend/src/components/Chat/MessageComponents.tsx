import React from 'react';
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot } from "lucide-react";

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

export const LLMResponseMessage: React.FC<{ data: LLMResponseData }> = ({ data }) => {
  return (
    <div className="animate-in slide-in-from-bottom-2 duration-300">
      <div className="prose prose-sm max-w-none text-gray-800 dark:text-gray-200">
        <div className="whitespace-pre-wrap leading-relaxed text-sm">
          {data.content}
        </div>
        {data.usage && (
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-3 pt-2 border-t border-gray-200 dark:border-gray-700 flex gap-4">
            <span>Tokens: {data.usage.usage.total_tokens}</span>
            <span>Cost: ${data.usage.cost.toFixed(4)}</span>
          </div>
        )}
      </div>
    </div>
  );
};

// Tool Result Message
interface ToolResultData extends BaseMessageData {
  tool_name: string;
  result: any;
  success: boolean;
  execution_time?: string;
  arguments?: Record<string, any>;
}

export const ToolResultMessage: React.FC<{ data: ToolResultData }> = ({ data }) => {
  return (
    <div className="animate-in slide-in-from-bottom-2 duration-300">
      <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
        <div className="text-xs font-medium text-gray-600 dark:text-gray-300 mb-2">
          Tool Result: {data.tool_name}
        </div>
        <div className="text-sm leading-relaxed text-gray-800 dark:text-gray-200">
          {typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2)}
        </div>
        {data.execution_time && (
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-2 pt-2 border-t border-gray-200 dark:border-gray-600">
            Execution time: {data.execution_time}
          </div>
        )}
      </div>
    </div>
  );
};

// LLM Chunk Message (for streaming)
interface LLMChunkData extends BaseMessageData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
}

export const LLMChunkMessage: React.FC<{ data: LLMChunkData }> = ({ data }) => {
  // This component is used for accumulating streaming chunks
  // In practice, chunks would be handled by the parent component to build complete messages
  return (
    <div className="animate-in slide-in-from-bottom-2 duration-300">
      <div className="prose prose-sm max-w-none text-gray-800 dark:text-gray-200">
        <div className="text-sm leading-relaxed whitespace-pre-wrap">
          {data.chunk}
          {!data.is_final && (
            <span className="inline-block w-2 h-5 bg-blue-600 animate-pulse ml-0.5 align-text-bottom"></span>
          )}
        </div>
        {!data.is_final && (
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-2">
            Thinking...
          </div>
        )}
      </div>
    </div>
  );
};

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
}

export const ErrorMessage: React.FC<{ data: ErrorData }> = ({ data }) => {
  // Determine icon based on error type
  const getErrorIcon = () => {
    if (data.is_auth_error) return '🔑';
    if (data.is_rate_limit_error) return '⏱️';
    if (data.is_quota_error) return '💳';
    if (data.is_model_error) return '🤖';
    if (data.is_network_error) return '🌐';
    return '⚠️';
  };

  const getErrorStyles = () => {
    if (data.retryable !== false) {
      return {
        container: "bg-yellow-50 dark:bg-yellow-950/30 border-yellow-200 dark:border-yellow-800",
        text: "text-yellow-700 dark:text-yellow-300"
      };
    }
    return {
      container: "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800", 
      text: "text-red-700 dark:text-red-300"
    };
  };

  const styles = getErrorStyles();

  return (
    <div className="animate-in slide-in-from-bottom-2 duration-300">
      <div className={`rounded-lg border p-4 ${styles.container}`}>
        <div className={`text-sm leading-relaxed ${styles.text} flex items-center gap-2`}>
          <span>{getErrorIcon()}</span>
          {data.error}
        </div>
        <div className="flex flex-wrap gap-2 mt-2 text-xs text-gray-600 dark:text-gray-400">
          {data.error_type && <span>Type: {data.error_type}</span>}
          {data.retryable !== undefined && (
            <span className={data.retryable ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400'}>
              {data.retryable ? 'Retryable' : 'Non-retryable'}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

// Workflow Result Message
interface WorkflowResultData extends BaseMessageData {
  result?: string;
  final_response?: string;
  success: boolean;
  iterations_completed?: number;
  total_cost?: number;
}

export const WorkflowResultMessage: React.FC<{ data: WorkflowResultData }> = ({ data }) => {
  const content = data.result || data.final_response || '';
  
  return (
    <div className="animate-in slide-in-from-bottom-2 duration-300">
      <div className="prose prose-sm max-w-none text-gray-800 dark:text-gray-200">
        <div className="text-sm leading-relaxed whitespace-pre-wrap">
          {content}
        </div>
        {(data.iterations_completed || data.total_cost) && (
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-3 pt-2 border-t border-gray-200 dark:border-gray-700 flex gap-4">
            {data.iterations_completed && <span>Iterations: {data.iterations_completed}</span>}
            {data.total_cost && <span>Total Cost: ${data.total_cost.toFixed(4)}</span>}
          </div>
        )}
      </div>
    </div>
  );
};

// System Message (for workflow events, debugging, etc.)
interface SystemData extends BaseMessageData {
  message: string;
  level?: 'info' | 'warning' | 'error';
}

export const SystemMessage: React.FC<{ data: SystemData }> = ({ data }) => {
  const levelColors = {
    info: 'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-300 dark:bg-blue-950/30 dark:border-blue-800',
    warning: 'text-yellow-600 bg-yellow-50 border-yellow-200 dark:text-yellow-300 dark:bg-yellow-950/30 dark:border-yellow-800', 
    error: 'text-red-600 bg-red-50 border-red-200 dark:text-red-300 dark:bg-red-950/30 dark:border-red-800'
  };
  
  const levelClass = levelColors[data.level || 'info'];
  
  return (
    <div className="flex justify-center my-4">
      <div className={`px-3 py-1.5 rounded-full text-xs font-medium border ${levelClass}`}>
        {data.message}
      </div>
    </div>
  );
};

// Export all message component types
export type MessageComponentType = 
  | { type: 'llm_response'; data: LLMResponseData }
  | { type: 'llm_chunk'; data: LLMChunkData }
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