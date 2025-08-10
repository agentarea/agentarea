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
    <div className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300">
      <Avatar className="h-8 w-8 border-2 border-primary/20">
        <AvatarFallback className="bg-primary/10">
          <Bot className="h-4 w-4 text-primary" />
        </AvatarFallback>
      </Avatar>
      <div className="max-w-[80%] rounded-2xl px-4 py-3 shadow-sm bg-background border border-border">
        <div className="text-sm leading-relaxed whitespace-pre-wrap">
          {data.content}
        </div>
        {data.usage && (
          <div className="text-xs text-muted-foreground mt-2 flex gap-4">
            <span>Tokens: {data.usage.usage.total_tokens}</span>
            <span>Cost: ${data.usage.cost.toFixed(4)}</span>
          </div>
        )}
        <p className="text-xs opacity-70 mt-2">
          {new Date(data.timestamp).toLocaleTimeString()}
        </p>
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
    <div className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300">
      <Avatar className="h-8 w-8 border-2 border-primary/20">
        <AvatarFallback className="bg-primary/10">
          <Bot className="h-4 w-4 text-primary" />
        </AvatarFallback>
      </Avatar>
      <div className="max-w-[80%] rounded-2xl px-4 py-3 shadow-sm bg-background border border-border">
        <div className="text-xs text-muted-foreground font-medium mb-2">
          Tool: {data.tool_name}
        </div>
        <div className="text-sm leading-relaxed">
          {typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2)}
        </div>
        {data.execution_time && (
          <div className="text-xs text-muted-foreground mt-2">
            Execution time: {data.execution_time}
          </div>
        )}
        <p className="text-xs opacity-70 mt-2">
          {new Date(data.timestamp).toLocaleTimeString()}
        </p>
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
    <div className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300">
      <Avatar className="h-8 w-8 border-2 border-primary/20">
        <AvatarFallback className="bg-primary/10">
          <Bot className="h-4 w-4 text-primary" />
        </AvatarFallback>
      </Avatar>
      <div className="max-w-[80%] rounded-2xl px-4 py-3 shadow-sm bg-background border border-border">
        <div className="text-sm leading-relaxed">
          {data.chunk}
          {!data.is_final && <span className="animate-pulse">|</span>}
        </div>
        <p className="text-xs opacity-70 mt-2">
          {data.is_final ? 'Completed' : 'Streaming...'}
        </p>
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

  const getBorderColor = () => {
    if (data.retryable !== false) return 'border-yellow-200'; // Retryable errors in yellow
    return 'border-destructive/20'; // Non-retryable errors in red
  };

  const getBackgroundColor = () => {
    if (data.retryable !== false) return 'bg-yellow-50';
    return 'bg-destructive/5';
  };

  const getTextColor = () => {
    if (data.retryable !== false) return 'text-yellow-700';
    return 'text-destructive';
  };

  return (
    <div className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300">
      <Avatar className="h-8 w-8 border-2 border-destructive/20">
        <AvatarFallback className="bg-destructive/10">
          <Bot className="h-4 w-4 text-destructive" />
        </AvatarFallback>
      </Avatar>
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 shadow-sm ${getBackgroundColor()} border ${getBorderColor()}`}>
        <div className={`text-sm leading-relaxed ${getTextColor()} flex items-center gap-2`}>
          <span>{getErrorIcon()}</span>
          {data.error}
        </div>
        <div className="flex flex-wrap gap-2 mt-2 text-xs opacity-70">
          {data.error_type && <span>Type: {data.error_type}</span>}
          {data.retryable !== undefined && (
            <span className={data.retryable ? 'text-yellow-600' : 'text-red-600'}>
              {data.retryable ? 'Retryable' : 'Non-retryable'}
            </span>
          )}
        </div>
        <p className="text-xs opacity-70 mt-2">
          {new Date(data.timestamp).toLocaleTimeString()}
        </p>
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
    <div className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300">
      <Avatar className="h-8 w-8 border-2 border-primary/20">
        <AvatarFallback className="bg-primary/10">
          <Bot className="h-4 w-4 text-primary" />
        </AvatarFallback>
      </Avatar>
      <div className="max-w-[80%] rounded-2xl px-4 py-3 shadow-sm bg-background border border-border">
        <div className="text-sm leading-relaxed whitespace-pre-wrap">
          {content}
        </div>
        <div className="text-xs text-muted-foreground mt-2 flex gap-4">
          {data.iterations_completed && <span>Iterations: {data.iterations_completed}</span>}
          {data.total_cost && <span>Total Cost: ${data.total_cost.toFixed(4)}</span>}
        </div>
        <p className="text-xs opacity-70 mt-2">
          {new Date(data.timestamp).toLocaleTimeString()}
        </p>
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
    info: 'text-blue-600 bg-blue-50 border-blue-200',
    warning: 'text-yellow-600 bg-yellow-50 border-yellow-200', 
    error: 'text-red-600 bg-red-50 border-red-200'
  };
  
  const levelClass = levelColors[data.level || 'info'];
  
  return (
    <div className="flex justify-center my-2">
      <div className={`px-3 py-1 rounded-full text-xs border ${levelClass}`}>
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