import React from 'react';
import { MessageWrapper } from './MessageWrapper';

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
    <MessageWrapper>
      <div className="rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md bg-background border border-border">
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
    </MessageWrapper>
  );
};

// Tool Call Started Message
interface ToolCallStartedData extends BaseMessageData {
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
}

export const ToolCallStartedMessage: React.FC<{ data: ToolCallStartedData }> = ({ data }) => {
  return (
    <MessageWrapper>
      <div className="bg-blue-50 dark:bg-blue-950/30 rounded-2xl border border-blue-200 dark:border-blue-800 p-4 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-medium text-blue-700 dark:text-blue-300 mb-2">
          <div className="w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          Calling {data.tool_name}...
        </div>
        {Object.keys(data.arguments).length > 0 && (
          <div className="text-xs text-blue-600 dark:text-blue-400 mt-2">
            <details className="cursor-pointer">
              <summary className="hover:text-blue-700 dark:hover:text-blue-300">Arguments</summary>
              <pre className="mt-1 p-2 bg-blue-100 dark:bg-blue-900/50 rounded text-blue-800 dark:text-blue-200 overflow-x-auto">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </div>
    </MessageWrapper>
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
  const formatResult = (result: any) => {
    if (typeof result === 'string') {
      return result;
    }
    return JSON.stringify(result, null, 2);
  };

  const getStatusColor = () => {
    if (data.success === false) {
      return {
        container: "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800",
        header: "text-red-700 dark:text-red-300",
        content: "text-red-800 dark:text-red-200",
        icon: "❌"
      };
    }
    return {
      container: "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800",
      header: "text-green-700 dark:text-green-300",
      content: "text-green-800 dark:text-green-200",
      icon: "✅"
    };
  };

  const colors = getStatusColor();

  return (
    <MessageWrapper>
      <div className={`rounded-2xl border p-4 shadow-sm ${colors.container}`}>
        <div className={`flex items-center gap-2 text-sm font-medium mb-2 ${colors.header}`}>
          <span>{colors.icon}</span>
          Tool Result: {data.tool_name}
        </div>
        <div className={`text-sm leading-relaxed ${colors.content}`}>
          <pre className="whitespace-pre-wrap overflow-x-auto">
            {formatResult(data.result)}
          </pre>
        </div>
        {Object.keys(data.arguments || {}).length > 0 && (
          <div className="mt-3 pt-2 border-t border-current/20">
            <details className="cursor-pointer">
              <summary className={`text-xs ${colors.header} hover:opacity-80`}>Arguments</summary>
              <pre className="mt-1 p-2 bg-black/5 dark:bg-white/5 rounded text-xs overflow-x-auto">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          </div>
        )}
        {data.execution_time && (
          <div className={`text-xs mt-2 pt-2 border-t border-current/20 ${colors.header}`}>
            Execution time: {data.execution_time}
          </div>
        )}
      </div>
    </MessageWrapper>
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
    <MessageWrapper>
      <div className="rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md bg-background border border-border">
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
    </MessageWrapper>
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
  tool_name?: string;
  arguments?: Record<string, any>;
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
    <MessageWrapper>
      <div className={`rounded-2xl border p-4 shadow-sm ${styles.container}`}>
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
    </MessageWrapper>
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
    <MessageWrapper>
      <div className="rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md bg-background border border-border">
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
    </MessageWrapper>
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