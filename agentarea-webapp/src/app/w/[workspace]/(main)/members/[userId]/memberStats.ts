import { getTaskStatusPresentation } from "@/lib/status";

type TaskLike = {
  status: string;
  created_at: string;
  total_cost?: number | null;
  result?: unknown;
};

export interface MemberTaskSummary {
  /** Tasks counted, at most the sample size. */
  count: number;
  /** More tasks exist than were counted; figures cover the newest `count`. */
  capped: boolean;
  running: number;
  needsAction: number;
  spend: number;
  lastStartedAt: string | null;
}

function taskCost(task: TaskLike): number {
  const fromResult =
    task.result && typeof task.result === "object"
      ? (task.result as { total_cost?: unknown }).total_cost
      : undefined;
  const cost = Number(task.total_cost ?? fromResult ?? 0);
  return Number.isFinite(cost) ? cost : 0;
}

/**
 * What a member's tasks add up to. `tasks` is the newest first page, fetched
 * one past `sampleSize` so a full page is told apart from a capped one.
 */
export function summarizeMemberTasks(
  tasks: TaskLike[],
  sampleSize: number
): MemberTaskSummary {
  const counted = tasks.slice(0, sampleSize);
  let running = 0;
  let needsAction = 0;
  let spend = 0;
  let lastStartedAt: string | null = null;
  for (const task of counted) {
    const kind = getTaskStatusPresentation(task.status).kind;
    if (kind === "running") running += 1;
    if (kind === "attention") needsAction += 1;
    spend += taskCost(task);
    if (
      !lastStartedAt ||
      Date.parse(task.created_at) > Date.parse(lastStartedAt)
    ) {
      lastStartedAt = task.created_at;
    }
  }
  return {
    count: counted.length,
    capped: tasks.length > sampleSize,
    running,
    needsAction,
    spend,
    lastStartedAt,
  };
}

/** The later of two instants, either of which may be missing. */
export function latestInstant(
  ...values: (string | null | undefined)[]
): string | null {
  let latest: string | null = null;
  for (const value of values) {
    if (!value || Number.isNaN(Date.parse(value))) continue;
    if (!latest || Date.parse(value) > Date.parse(latest)) latest = value;
  }
  return latest;
}

export type GrantRelation = "owner" | "editor" | "user";

export interface MemberGrant {
  namespace: string;
  object: string;
  objectName: string;
  relation: GrantRelation;
}

const GRANT_RANK: Record<GrantRelation, number> = {
  owner: 0,
  editor: 1,
  user: 2,
};

function isGrantRelation(value: string): value is GrantRelation {
  return value in GRANT_RANK;
}

/**
 * The resources granted to this person directly, strongest grant first. The
 * graph names a person `user:<id>`; one resource held twice keeps its stronger
 * grant.
 */
export function memberGrants(
  relationships: {
    namespace: string;
    object: string;
    object_name: string;
    relation: string;
    subject: string;
  }[],
  userId: string
): MemberGrant[] {
  const strongest = new Map<string, MemberGrant>();
  for (const r of relationships) {
    if (r.subject !== `user:${userId}` || !isGrantRelation(r.relation))
      continue;
    const key = `${r.namespace}:${r.object}`;
    const held = strongest.get(key);
    if (held && GRANT_RANK[held.relation] <= GRANT_RANK[r.relation]) continue;
    strongest.set(key, {
      namespace: r.namespace,
      object: r.object,
      objectName: r.object_name,
      relation: r.relation,
    });
  }
  return [...strongest.values()].sort(
    (a, b) =>
      GRANT_RANK[a.relation] - GRANT_RANK[b.relation] ||
      a.objectName.localeCompare(b.objectName)
  );
}
