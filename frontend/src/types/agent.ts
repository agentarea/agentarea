export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  instruction?: string | null;
  model_id?: string | null;
  icon?: string;
  tools_config?: Record<string, any> | null;
  events_config?: Record<string, any> | null;
  planning?: boolean | null;
} 