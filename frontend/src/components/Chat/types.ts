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