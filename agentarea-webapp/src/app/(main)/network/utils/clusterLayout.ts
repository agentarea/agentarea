interface NodeRef {
  id: string;
  type: string;
  label: string;
}

interface EdgeRef {
  id: string;
  source: string;
  target: string;
  relation: string;
}

export type Lane = "events" | "agents" | "external";

interface LayoutOptions {
  laneX: Record<Lane, number>;
  rowHeight: number;
  clusterGap: number;
  iterations?: number;
}

interface ClusterBand {
  id: string;
  yStart: number;
  yEnd: number;
  rows: number;
  members: NodeRef[];
}

export interface LayoutResult {
  positions: Record<string, { x: number; y: number }>;
  clusters: ClusterBand[];
}

function getLane(node: NodeRef): Lane {
  if (node.type === "trigger") return "events";
  if (node.type === "agent") return "agents";
  return "external";
}

function unionFind(nodes: NodeRef[], edges: EdgeRef[]) {
  const parent: Record<string, string> = {};
  for (const n of nodes) parent[n.id] = n.id;
  const find = (x: string): string => {
    while (parent[x] !== x) {
      parent[x] = parent[parent[x]];
      x = parent[x];
    }
    return x;
  };
  for (const e of edges) {
    if (parent[e.source] === undefined || parent[e.target] === undefined) continue;
    const ra = find(e.source);
    const rb = find(e.target);
    if (ra !== rb) parent[ra] = rb;
  }
  const componentOf: Record<string, string> = {};
  for (const n of nodes) componentOf[n.id] = find(n.id);
  return componentOf;
}

function median(arr: number[]): number | null {
  if (arr.length === 0) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = s.length;
  if (m % 2 === 1) return s[(m - 1) / 2];
  return (s[m / 2 - 1] + s[m / 2]) / 2;
}

interface Adjacency {
  /** Y-providers from layers we read FROM during forward sweep on this lane. */
  forward: Record<string, string[]>;
  /** Y-providers from layers we read FROM during backward sweep. */
  backward: Record<string, string[]>;
  /** Same-lane peers (e.g. agent ↔ agent via delegation) — used to pull peers together. */
  peers: Record<string, string[]>;
}

function buildAdjacency(
  members: NodeRef[],
  edges: EdgeRef[]
): { events: Adjacency; agents: Adjacency; external: Adjacency } {
  const idSet = new Set(members.map((m) => m.id));
  const eventIds = new Set(members.filter((m) => m.type === "trigger").map((m) => m.id));
  const agentIds = new Set(members.filter((m) => m.type === "agent").map((m) => m.id));
  const externalIds = new Set(
    members.filter((m) => m.type !== "trigger" && m.type !== "agent").map((m) => m.id)
  );

  const events: Adjacency = { forward: {}, backward: {}, peers: {} };
  const agents: Adjacency = { forward: {}, backward: {}, peers: {} };
  const external: Adjacency = { forward: {}, backward: {}, peers: {} };

  const push = (m: Record<string, string[]>, k: string, v: string) => {
    (m[k] ||= []).push(v);
  };

  for (const e of edges) {
    if (!idSet.has(e.source) || !idSet.has(e.target)) continue;
    if (e.relation === "has_trigger") {
      // topology: agent → trigger; visually we treat trigger as feeding agent.
      const agentId = e.source;
      const triggerId = e.target;
      if (!agentIds.has(agentId) || !eventIds.has(triggerId)) continue;
      push(events.forward, triggerId, agentId); // pull trigger toward its agent
      push(agents.backward, agentId, triggerId); // pull agent toward its triggers
    } else if (e.relation === "delegates_to") {
      const parent = e.source;
      const child = e.target;
      if (!agentIds.has(parent) || !agentIds.has(child)) continue;
      push(agents.peers, parent, child);
      push(agents.peers, child, parent);
    } else if (
      e.relation === "uses_mcp" ||
      e.relation === "uses_openapi" ||
      e.relation === "has_skill"
    ) {
      const agentId = e.source;
      const extId = e.target;
      if (!agentIds.has(agentId) || !externalIds.has(extId)) continue;
      push(agents.forward, agentId, extId); // agent considers its externals (forward sweep)
      push(external.backward, extId, agentId); // external pulls toward consumer
    }
  }
  return { events, agents, external };
}

interface OrderedLane {
  items: NodeRef[];
  index: Record<string, number>;
}

function reorder(
  lane: OrderedLane,
  adjacency: Adjacency,
  yOf: (id: string) => number,
  direction: "forward" | "backward"
) {
  const sources = direction === "forward" ? adjacency.forward : adjacency.backward;
  const peers = adjacency.peers;
  const scored = lane.items.map((item) => {
    const refs: number[] = [];
    for (const id of sources[item.id] || []) refs.push(yOf(id));
    for (const id of peers[item.id] || []) refs.push(yOf(id));
    const score = median(refs);
    return {
      item,
      score: score ?? lane.index[item.id],
    };
  });
  scored.sort((a, b) => {
    if (a.score !== b.score) return a.score - b.score;
    return a.item.label.localeCompare(b.item.label);
  });
  lane.items = scored.map((s) => s.item);
  lane.index = {};
  scored.forEach((s, i) => {
    lane.index[s.item.id] = i;
  });
}

export function layoutClusters(
  nodes: NodeRef[],
  edges: EdgeRef[],
  opts: LayoutOptions
): LayoutResult {
  const { laneX, rowHeight, clusterGap } = opts;
  const ITER = opts.iterations ?? 12;

  const componentOf = unionFind(nodes, edges);
  const byCluster: Record<string, NodeRef[]> = {};
  for (const n of nodes) (byCluster[componentOf[n.id]] ||= []).push(n);

  const clusterIds = Object.keys(byCluster).sort((a, b) => {
    const sizeDiff = byCluster[b].length - byCluster[a].length;
    if (sizeDiff !== 0) return sizeDiff;
    const aLabel = [...byCluster[a]]
      .sort((x, y) => x.label.localeCompare(y.label))[0].label;
    const bLabel = [...byCluster[b]]
      .sort((x, y) => x.label.localeCompare(y.label))[0].label;
    return aLabel.localeCompare(bLabel);
  });

  const positions: Record<string, { x: number; y: number }> = {};
  const clusters: ClusterBand[] = [];
  let clusterY = 0;

  for (const cid of clusterIds) {
    const members = byCluster[cid];
    const eventNodes = members.filter((m) => m.type === "trigger");
    const agentNodes = members.filter((m) => m.type === "agent");
    const externalNodes = members.filter(
      (m) => m.type !== "trigger" && m.type !== "agent"
    );

    const adjacency = buildAdjacency(members, edges);

    const initLane = (items: NodeRef[]): OrderedLane => {
      const sorted = [...items].sort((a, b) => a.label.localeCompare(b.label));
      const index: Record<string, number> = {};
      sorted.forEach((it, i) => (index[it.id] = i));
      return { items: sorted, index };
    };

    const events = initLane(eventNodes);
    const agents = initLane(agentNodes);
    const external = initLane(externalNodes);

    const yOfFactory = () => (id: string): number => {
      if (events.index[id] !== undefined) return events.index[id];
      if (agents.index[id] !== undefined) return agents.index[id];
      return external.index[id] ?? 0;
    };

    for (let i = 0; i < ITER; i++) {
      const yOf = yOfFactory();
      // Forward: events → agents → external
      reorder(agents, adjacency.agents, yOf, "forward");
      reorder(external, adjacency.external, yOfFactory(), "backward");
      // Backward: external → agents → events
      reorder(agents, adjacency.agents, yOfFactory(), "backward");
      reorder(events, adjacency.events, yOfFactory(), "forward");
    }

    const rows = Math.max(events.items.length, agents.items.length, external.items.length, 1);

    const placeLane = (lane: OrderedLane, x: number) => {
      const offset = ((rows - lane.items.length) / 2) * rowHeight;
      lane.items.forEach((item, i) => {
        positions[item.id] = { x, y: clusterY + offset + i * rowHeight };
      });
    };
    placeLane(events, laneX.events);
    placeLane(agents, laneX.agents);
    placeLane(external, laneX.external);

    clusters.push({
      id: cid,
      yStart: clusterY,
      yEnd: clusterY + rows * rowHeight,
      rows,
      members,
    });

    clusterY += rows * rowHeight + clusterGap;
  }

  return { positions, clusters };
}

export { getLane };
