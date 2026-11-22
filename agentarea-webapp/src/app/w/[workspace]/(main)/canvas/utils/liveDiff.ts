import type { OrgSource } from "./canvasState";

type LiveTask = {
  id: string;
  agentId: string;
  title: string;
  status: string;
  source: OrgSource;
  totalCost: number | null;
};

export type Happening =
  | {
      kind: "event";
      id: string;
      at: number;
      summary: string;
      agentIds: string[];
    }
  | {
      kind: "task";
      id: string;
      at: number;
      taskId: string;
      agentId: string;
      title: string;
      source: OrgSource;
    }
  | {
      kind: "status";
      id: string;
      at: number;
      taskId: string;
      agentId: string;
      title: string;
      status: string;
    }
  | { kind: "cost"; id: string; at: number; agentId: string; delta: number };

const COST_EPSILON = 0.000001;

/**
 * What changed between two reads of the recent tasks: tasks that appeared,
 * tasks whose status moved, and how much each agent's spend grew.
 */
export function diffTasks(
  previous: LiveTask[],
  next: LiveTask[],
  at: number
): Happening[] {
  const before = new Map(previous.map((task) => [task.id, task]));
  const happenings: Happening[] = [];
  const spend = new Map<string, number>();

  for (const task of next) {
    const old = before.get(task.id);
    const delta = (task.totalCost ?? 0) - (old?.totalCost ?? 0);
    if (delta > COST_EPSILON) {
      spend.set(task.agentId, (spend.get(task.agentId) ?? 0) + delta);
    }
    if (!old) {
      happenings.push({
        kind: "task",
        id: `task:${task.id}:${at}`,
        at,
        taskId: task.id,
        agentId: task.agentId,
        title: task.title,
        source: task.source,
      });
    } else if (old.status !== task.status) {
      happenings.push({
        kind: "status",
        id: `status:${task.id}:${task.status}:${at}`,
        at,
        taskId: task.id,
        agentId: task.agentId,
        title: task.title,
        status: task.status,
      });
    }
  }

  for (const [agentId, delta] of spend) {
    happenings.push({
      kind: "cost",
      id: `cost:${agentId}:${at}`,
      at,
      agentId,
      delta,
    });
  }
  return happenings;
}
