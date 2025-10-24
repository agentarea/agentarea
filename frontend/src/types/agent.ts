export interface ModelInfo {
  provider_name?: string;
  model_display_name?: string;
  config_name?: string;
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
  tools_config?: Record<string, any> | null;
  events_config?: Record<string, any> | null;
  planning?: boolean | null;
}
