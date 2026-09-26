import type { AgentUpdate, TriggerSpec } from "@/api/client/types.gen";

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
  // null = every tool of the server, including ones it adds later; [] = none
  allowed_tools: MCPToolConfig[] | null;
};

/**
 * OpenAPI Connection configuration type
 */
export type OpenAPIConfig = {
  openapi_connection_id: string;
  openapi_connection_name?: string;  // resolved name for backend; filled by picker
  allowed_tools: string[] | null;  // operation names; null = all, including ones added later; [] = none
  // Disclosure mode (issue #115). "searchable" defers operation schemas
  // behind a `load_tools` meta-tool; "explicit" sends every schema every call.
  // Absent = legacy explicit behavior preserved.
  load_mode?: "explicit" | "searchable";
  requires_user_confirmation?: boolean;
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
    // Tools this form does not edit (e.g. delegation), sent back unchanged.
    carried_tools?: NonNullable<AgentUpdate["tools"]>;
  };
  planning: boolean;
  a2ui_enabled: boolean;
  skills?: AgentSkill[];
  // Created together with the agent; an existing agent's triggers live on /triggers
  triggers?: TriggerSpec[];
};

