import type { components } from "@/api/schema";
import type { AddAgentFormState } from "./actions";

/**
 * Event configuration type
 */
export type EventConfig = {
  event_type: string;
  config?: Record<string, unknown> | null;
  enabled?: boolean;
};

/**
 * MCP Tool configuration type
 */
export type MCPToolConfig = {
  tool_name: string;
  requires_user_confirmation?: boolean;
};

/**
 * MCP Server configuration type
 */
export type MCPServerConfig = {
  mcp_server_id: string;
  allowed_tools?: MCPToolConfig[];
};

/**
 * Builtin Tool configuration type
 */
export type BuiltinToolConfig = {
  tool_name: string;
  requires_user_confirmation?: boolean;
  enabled?: boolean;
  disabled_methods?: { [methodName: string]: boolean };
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
    builtin_tools?: BuiltinToolConfig[];
  };
  events_config: {
    events: EventConfig[];
  };
  planning: boolean;
};

// Default form state matching AgentCreate schema closely
export const initialState: AddAgentFormState = {
  message: "",
  errors: {},
  fieldValues: {
    name: "",
    description: "",
    instruction: "",
    model_id: "",
    tools_config: { mcp_server_configs: [] }, // Initialize as object with empty array
    events_config: { events: [] }, // Array of event config objects
    planning: false,
  },
};
