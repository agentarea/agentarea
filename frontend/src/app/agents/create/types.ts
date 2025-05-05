import type { components } from '@/api/schema';

/**
 * Event configuration type
 */
export type EventConfig = {
  event_type: string;
  config?: Record<string, unknown> | null;
};

/**
 * MCP Server configuration type
 */
export type MCPServerConfig = {
  mcp_server_id: string;
  api_key: string;
  config?: Record<string, unknown> | null;
};

/**
 * Main form values for agent creation
 * Extends the API's AgentCreate type with our custom instruction field
 */
export type AgentFormValues = {
  name: string;
  description: string;
  instruction: string;
  model_id: string;
  tools_config: {
    mcp_server_configs: MCPServerConfig[];
  };
  events_config: {
    events: EventConfig[];
  };
  planning: boolean;
}; 