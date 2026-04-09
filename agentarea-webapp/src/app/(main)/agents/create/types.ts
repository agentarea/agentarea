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
 * OpenAPI Connection configuration type
 */
export type OpenAPIConfig = {
  openapi_connection_id: string;
  openapi_connection_name?: string;  // resolved name for backend; filled by picker
  allowed_tools?: string[];  // operation names; empty/missing = all
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
 * Agent skill reference for form state
 */
export type AgentSkill = {
  id: string;
  name: string;
  description?: string | null;
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
    openapi_configs?: OpenAPIConfig[];
  };
  events_config: {
    events: EventConfig[];
  };
  planning: boolean;
  a2ui_enabled: boolean;
  skills?: AgentSkill[];
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
    a2ui_enabled: false,
  },
};
