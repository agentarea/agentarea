export interface Task {
  id: string;
  description?: string;
  agent_id: string;
  agent_name?: string;
  agent_description?: string;
  created_at?: string;
  execution_id?: string | null;
  result?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
}
