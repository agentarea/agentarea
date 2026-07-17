export interface Task {
  id: string;
  description: string;
  status: string;
  created_at: string;
  agent_id: string;
}

export interface TaskStatus {
  task_id: string;
  agent_id: string;
  execution_id: string;
  status: string;
  start_time?: string;
  end_time?: string;
  execution_time?: string;
  error?: string;
  result?: unknown;
  message?: string;
  artifacts?: unknown;
  session_id?: string;
  usage_metadata?: unknown;
}

export interface TaskWithStatus extends Task {
  taskStatus?: TaskStatus;
}
