export interface ModelInfo {
  provider_name?: string;
  model_display_name?: string;
  config_name?: string;
}

export interface ToolSettings {
  disabled_methods?: string[];  // For code tools
  allowed_tools?: string[];     // For MCP tools
}

export interface ToolConfig {
  type: 'code' | 'mcp' | 'openapi';
  name: string;
  settings?: ToolSettings;
}

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  instruction?: string | null;
  model_id?: string | null;
  model_info?: ModelInfo | null;
  icon?: string;
  tools?: ToolConfig[] | null;
  // TODO: Consolidate tools vs tools_config
  tools_config?: {
    builtin_tools?: Array<{ tool_name: string; [key: string]: any }>;
    mcp_server_configs?: Array<{ server_id: string; tools?: string[]; [key: string]: any }>;
    openapi_configs?: Array<{ openapi_connection_id: string; allowed_tools?: string[]; [key: string]: any }>;
    [key: string]: any;
  } | null;
  events_config?: Record<string, any> | null;
  planning?: boolean | null;
  a2ui_enabled?: boolean | null;
  skills?: Array<{ id: string; name: string; description?: string | null }> | null;
}
