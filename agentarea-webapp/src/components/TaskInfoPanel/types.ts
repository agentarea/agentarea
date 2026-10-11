import type { TaskProvenance } from "@/api/client/types.gen";

/** The person who started a task, resolved for display. */
export interface TaskRequester {
  /** tasks.created_by */
  id: string;
  /** Display name; null when nothing could resolve the id. */
  name: string | null;
  /** The viewer is this person. */
  isCurrentUser: boolean;
}

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
  /** Who or what started this task — a trigger, a delegating task, or a person. */
  provenance?: TaskProvenance | null;
  /** The person who started it; null when the task names nobody. */
  requester?: TaskRequester | null;
}
