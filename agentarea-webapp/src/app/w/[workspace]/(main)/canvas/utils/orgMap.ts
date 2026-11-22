import { getTaskStatusPresentation } from "@/lib/status";
import type { TaskSourceKind } from "@/lib/taskSource";
import {
  GAP,
  ORG_SOURCES,
  TILE_SIZE,
  tileAt,
  type Canvas,
  type Link,
  type OrgSource,
  type Tile,
} from "./canvasState";

export type OrgAgent = { id: string; name: string; connectionIds: string[] };
export type OrgTrigger = {
  id: string;
  name: string;
  source: OrgSource;
  agentId: string;
  active: boolean;
  /** The stream a stream trigger listens on; events on it reach this agent. */
  streamId: string | null;
};
export type OrgTask = {
  agentId: string;
  agentName: string | null;
  status: string;
  source: OrgSource;
  totalCost: number | null;
};

export function triggerSource(triggerType: string): OrgSource {
  if (triggerType === "stream") return "event";
  if (triggerType === "cron") return "schedule";
  return "webhook";
}

export function taskSource(kind: TaskSourceKind): OrgSource {
  switch (kind) {
    case "event":
      return "event";
    case "schedule":
      return "schedule";
    case "trigger":
      return "webhook";
    case "delegation":
      return "delegation";
    case "a2a":
      return "a2a";
    case "manual":
    case "manual_run":
      return "manual";
  }
}

export type AgentStats = {
  total: number;
  running: number;
  attention: number;
  done: number;
  failed: number;
  cost: number;
};

export function agentStats(tasks: OrgTask[], agentId: string): AgentStats {
  const stats: AgentStats = {
    total: 0,
    running: 0,
    attention: 0,
    done: 0,
    failed: 0,
    cost: 0,
  };
  for (const task of tasks) {
    if (task.agentId !== agentId) continue;
    stats.total += 1;
    stats.cost += task.totalCost ?? 0;
    const kind = getTaskStatusPresentation(task.status).kind;
    if (kind === "running" || kind === "queued") stats.running += 1;
    else if (kind === "attention") stats.attention += 1;
    else if (kind === "done") stats.done += 1;
    else if (kind === "failed") stats.failed += 1;
  }
  return stats;
}

export function sourceCounts(
  tasks: OrgTask[],
  triggers: OrgTrigger[],
  source: OrgSource,
  agentId?: string
): { tasks: number; triggers: number } {
  const forAgent = (id: string) => agentId === undefined || id === agentId;
  return {
    tasks: tasks.filter((t) => t.source === source && forAgent(t.agentId))
      .length,
    triggers: triggers.filter((t) => t.source === source && forAgent(t.agentId))
      .length,
  };
}

export type SpendRow = {
  agentId: string;
  agentName: string | null;
  tasks: number;
  cost: number;
};

/** Tasks and spend per agent, the most expensive first. */
export function agentSpendRows(tasks: OrgTask[]): SpendRow[] {
  const rows = new Map<string, SpendRow>();
  for (const task of tasks) {
    const row = rows.get(task.agentId) ?? {
      agentId: task.agentId,
      agentName: task.agentName,
      tasks: 0,
      cost: 0,
    };
    row.tasks += 1;
    row.cost += task.totalCost ?? 0;
    rows.set(task.agentId, row);
  }
  return [...rows.values()].sort(
    (a, b) => b.cost - a.cost || b.tasks - a.tasks
  );
}

const MAX_AGENTS = 10;
const COLUMN_GAP = 160;

export type OrgMapLabels = {
  sourcesHeader: string;
  agentsHeader: string;
  liveHeader: string;
  intro: string;
  introLink: string;
  flow: (counts: { tasks: number; triggers: number }) => string;
  liveLink: string;
  spendLink: string;
};

/**
 * "How the organisation works" laid out left to right: where work comes from,
 * the agents that do it, and what is happening right now. Arrows carry how
 * much flows along them; a header note sits over each column, and the tables
 * of spend and recent tasks sit beside and below.
 */
export function orgMap(options: {
  agents: OrgAgent[];
  triggers: OrgTrigger[];
  tasks: OrgTask[];
  newId: () => string;
  labels: OrgMapLabels;
}): Pick<Canvas, "tiles" | "links"> {
  const { agents, triggers, tasks, newId, labels } = options;
  const tiles: Tile[] = [];
  const links: Link[] = [];
  const top = 170;

  const activity = (agentId: string) =>
    tasks.filter((t) => t.agentId === agentId).length +
    triggers.filter((t) => t.agentId === agentId).length;
  const busy = agents.filter((agent) => activity(agent.id) > 0);
  const chosen = (busy.length > 0 ? busy : agents)
    .map((agent, index) => ({ agent, index, score: activity(agent.id) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, MAX_AGENTS)
    .map(({ agent }) => agent);

  const sources = ORG_SOURCES.filter((source) => {
    const counts = sourceCounts(tasks, triggers, source);
    return counts.tasks + counts.triggers > 0;
  });

  const sourceX = 0;
  const agentX = sourceX + TILE_SIZE.source.width + COLUMN_GAP;
  const liveX = agentX + TILE_SIZE.agent.width + COLUMN_GAP;
  const spendX = liveX + TILE_SIZE.activity.width + GAP;
  const header = { width: 300, height: 120 };

  tiles.push(
    ...[
      { x: sourceX, text: labels.sourcesHeader },
      { x: agentX, text: labels.agentsHeader },
      { x: liveX, text: labels.liveHeader },
    ].map(({ x, text }) =>
      tileAt({ kind: "note", text }, newId(), { x, y: 0 }, header)
    )
  );

  const sourceTiles = new Map<OrgSource, Tile>();
  sources.forEach((source, index) => {
    const tile = tileAt({ kind: "source", source }, newId(), {
      x: sourceX,
      y: top + index * (TILE_SIZE.source.height + 30),
    });
    sourceTiles.set(source, tile);
    tiles.push(tile);
  });

  const agentTiles = new Map<string, Tile>();
  chosen.forEach((agent, index) => {
    const tile = tileAt({ kind: "agent", agentId: agent.id }, newId(), {
      x: agentX,
      y: top + index * (TILE_SIZE.agent.height + 30),
    });
    agentTiles.set(agent.id, tile);
    tiles.push(tile);
  });

  for (const agent of chosen) {
    const agentTile = agentTiles.get(agent.id);
    if (!agentTile) continue;
    for (const source of sources) {
      const counts = sourceCounts(tasks, triggers, source, agent.id);
      const sourceTile = sourceTiles.get(source);
      if (!sourceTile || counts.tasks + counts.triggers === 0) continue;
      links.push({
        id: newId(),
        from: sourceTile.id,
        to: agentTile.id,
        label: labels.flow(counts),
      });
    }
  }

  const live = tileAt({ kind: "activity" }, newId(), { x: liveX, y: top });
  tiles.push(live);
  const firstAgent = chosen[0] && agentTiles.get(chosen[0].id);
  if (firstAgent) {
    links.push({
      id: newId(),
      from: firstAgent.id,
      to: live.id,
      label: labels.liveLink,
    });
  }

  const intro = tileAt(
    { kind: "note", text: labels.intro },
    newId(),
    { x: sourceX - TILE_SIZE.note.width - COLUMN_GAP, y: top },
    { width: TILE_SIZE.note.width, height: 190 }
  );
  tiles.push(intro);
  const firstSource = sourceTiles.get(sources[0]);
  if (firstSource) {
    links.push({
      id: newId(),
      from: intro.id,
      to: firstSource.id,
      label: labels.introLink,
    });
  }

  const spend = tileAt(
    { kind: "table", source: "agentSpend" },
    newId(),
    { x: spendX, y: top },
    { width: 520, height: TILE_SIZE.activity.height }
  );
  tiles.push(spend);
  links.push({
    id: newId(),
    from: live.id,
    to: spend.id,
    label: labels.spendLink,
  });

  const bottom = Math.max(
    ...tiles.map((tile) => tile.frame.y + tile.frame.height)
  );
  tiles.push(
    tileAt(
      { kind: "table", source: "tasks" },
      newId(),
      { x: sourceX, y: bottom + GAP * 2 },
      { width: spendX - sourceX + 520, height: 380 }
    )
  );

  return { tiles, links };
}
