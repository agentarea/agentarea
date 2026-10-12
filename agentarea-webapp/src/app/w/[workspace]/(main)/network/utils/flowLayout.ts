import dagre from "@dagrejs/dagre";
import type { GraphEdge, GraphNode, NetworkGraph } from "./networkGraph";
import {
  perimeterContour,
  skeleton,
  type Point,
  type Rect,
} from "./perimeterContour";

export type FlowZone = "inbound" | "inside" | "outbound";
export type FlowCrossing = "inbound" | "outbound";

export type { Point };

export interface FlowLabel {
  zone: "inbound";
  x: number;
  y: number;
  count: number;
}

export interface FlowLayout {
  positions: Map<string, Point>;
  /** Bend points of each edge, ends excluded, so it passes between nodes. */
  routes: Map<string, Point[]>;
  zones: Map<string, FlowZone>;
  /** Closed loops of the perimeter outline, holes included (even-odd). */
  perimeter: Point[][];
  insideCount: number;
  labels: FlowLabel[];
}

// The box a node takes up on the canvas: its circle and the label under it.
const LABEL_HALF_WIDTH = 64;
const LABEL_DEPTH = 22;

function compareText(a: string, b: string) {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Which side of the workspace's trust boundary a node is on. Inside: the
 * agents, the private resources they keep data in, and timers, which carry no
 * outside data. Outside on the way in: people and every trigger that brings
 * something from elsewhere (a webhook, a poll). Outside on the way out: every
 * resource that is not private — one whose scope nobody declared counts as
 * leaving, since a reader auditing transfers has to see it.
 */
export function flowZone(node: GraphNode): FlowZone {
  if (node.kind === "person") return "inbound";
  if (node.kind === "trigger")
    return node.triggerType === "cron" ? "inside" : "inbound";
  if (node.kind === "agent") return "inside";
  return node.scope === "private" ? "inside" : "outbound";
}

/** Whether a link carries data across the boundary, and which way. */
export function crossing(
  edge: GraphEdge,
  zones: Map<string, FlowZone>
): FlowCrossing | null {
  const source = zones.get(edge.source);
  const target = zones.get(edge.target);
  if (source === "inbound" && target === "inside") return "inbound";
  if (target === "outbound" && source !== "outbound") return "outbound";
  return null;
}

/**
 * How many hand-offs deep each agent sits: an agent nobody delegates to is 0,
 * its delegates 1, and so on. A cycle is cut where the walk first closes it.
 */
function delegationDepths(agents: GraphNode[], edges: GraphEdge[]) {
  const ids = new Set(agents.map((agent) => agent.id));
  const out = new Map<string, string[]>();
  for (const edge of [...edges].sort(
    (a, b) => compareText(a.source, b.source) || compareText(a.target, b.target)
  )) {
    if (
      edge.relation !== "delegates_to" ||
      !ids.has(edge.source) ||
      !ids.has(edge.target)
    ) {
      continue;
    }
    out.set(edge.source, [...(out.get(edge.source) ?? []), edge.target]);
  }

  const state = new Map<string, "open" | "done">();
  const incoming = new Map<string, string[]>();
  const visit = (id: string) => {
    state.set(id, "open");
    for (const next of out.get(id) ?? []) {
      if (state.get(next) === "open") continue;
      incoming.set(next, [...(incoming.get(next) ?? []), id]);
      if (!state.has(next)) visit(next);
    }
    state.set(id, "done");
  };
  for (const agent of agents) if (!state.has(agent.id)) visit(agent.id);

  const depths = new Map<string, number>();
  const depth = (id: string): number => {
    const known = depths.get(id);
    if (known !== undefined) return known;
    const value = Math.max(
      0,
      ...(incoming.get(id) ?? []).map((source) => depth(source) + 1)
    );
    depths.set(id, value);
    return value;
  };
  for (const agent of agents) depth(agent.id);
  return depths;
}

/**
 * The data-flow lens as a data-flow diagram with one trust boundary. Outside
 * sources stand on the left; each outside recipient stands just after the
 * agent that sends to it, so the line that leaves is short and leaves where
 * the sender is. The perimeter is a bubble around what is inside, grown along
 * the spanning tree of how those nodes connect and pushed back from every
 * outside node, so it bends around a recipient instead of swallowing it.
 * dagre orders each column and routes a long edge through the gaps, so a line
 * that skips columns never runs through a node it does not touch.
 */
export function flowLayout(
  graph: NetworkGraph,
  size: (node: GraphNode) => number
): FlowLayout {
  const zones = new Map(graph.nodes.map((node) => [node.id, flowZone(node)]));
  const nodes = [...graph.nodes].sort((a, b) => compareText(a.id, b.id));
  const agents = nodes.filter((node) => node.kind === "agent");
  const depths = delegationDepths(agents, graph.edges);

  // Columns order the reading, left to right; they are not the zones. A
  // private store sits right after the deepest agent that uses it, a timer
  // just before the agent it starts — the boundary is drawn around them.
  const raw = new Map<string, number>();
  for (const node of nodes) {
    const zone = zones.get(node.id);
    if (zone === "inbound") raw.set(node.id, 0);
    else if (node.kind === "trigger") raw.set(node.id, 1);
    else if (node.kind === "agent")
      raw.set(node.id, 2 + (depths.get(node.id) ?? 0));
  }
  for (const node of nodes) {
    if (zones.get(node.id) !== "inside" || raw.has(node.id)) continue;
    const users = graph.edges
      .filter((edge) => edge.target === node.id)
      .map((edge) => raw.get(edge.source))
      .filter((level): level is number => level !== undefined);
    raw.set(node.id, users.length ? Math.max(...users) + 1 : 2);
  }
  const insideEnd = Math.max(1, ...raw.values());
  for (const node of nodes) {
    if (zones.get(node.id) !== "outbound") continue;
    const senders = graph.edges
      .filter((edge) => edge.target === node.id)
      .map((edge) => raw.get(edge.source))
      .filter((level): level is number => level !== undefined);
    raw.set(node.id, (senders.length ? Math.max(...senders) : insideEnd) + 1);
  }
  const distinct = [...new Set(raw.values())].sort((a, b) => a - b);
  const levels = new Map(
    [...raw].map(([id, level]) => [id, distinct.indexOf(level)])
  );

  const layout = new dagre.graphlib.Graph({ multigraph: true });
  layout.setGraph({
    rankdir: "LR",
    nodesep: 26,
    edgesep: 12,
    ranksep: 150,
    marginx: 0,
    marginy: 0,
    // Ranks are ours, not dagre's: its own ranking would pull a source next to
    // the agent it starts, inside the boundary. Its pipeline doubles every rank
    // to leave room for edge labels, so ours are doubled to match; the nesting
    // root it adds sits before them all.
    ranker: ((g: dagre.graphlib.Graph) => {
      for (const id of g.nodes()) {
        const level = levels.get(id);
        g.node(id).rank = level === undefined ? -2 : level * 2;
      }
    }) as unknown as "network-simplex",
  });
  layout.setDefaultEdgeLabel(() => ({}));
  const sizes = new Map(nodes.map((node) => [node.id, size(node)]));
  for (const node of nodes) {
    const s = sizes.get(node.id) ?? 0;
    layout.setNode(node.id, { width: s + 96, height: s + 28 });
  }
  const forward = [...graph.edges]
    .filter(
      (edge) =>
        levels.has(edge.source) &&
        levels.has(edge.target) &&
        (levels.get(edge.target) ?? 0) > (levels.get(edge.source) ?? 0)
    )
    .sort((a, b) => compareText(a.id, b.id));
  for (const edge of forward) {
    layout.setEdge(edge.source, edge.target, {}, edge.id);
  }
  dagre.layout(layout);

  const positions = new Map<string, Point>();
  for (const node of nodes) {
    const { x, y } = layout.node(node.id);
    positions.set(node.id, { x, y });
  }
  const routes = new Map<string, Point[]>();
  for (const edge of forward) {
    const points =
      layout.edge({ v: edge.source, w: edge.target, name: edge.id })?.points ??
      [];
    routes.set(
      edge.id,
      points.slice(1, -1).map(({ x, y }: Point) => ({ x, y }))
    );
  }

  const box = (node: GraphNode): Rect => {
    const { x, y } = positions.get(node.id) as Point;
    const r = (sizes.get(node.id) ?? 0) / 2;
    const half = Math.max(r, LABEL_HALF_WIDTH);
    return { x1: x - half, y1: y - r, x2: x + half, y2: y + r + LABEL_DEPTH };
  };
  const inside = nodes.filter((node) => zones.get(node.id) === "inside");
  const outside = nodes.filter((node) => zones.get(node.id) !== "inside");
  const index = new Map(inside.map((node, i) => [node.id, i]));
  const linked = new Set(
    graph.edges.flatMap((edge) => {
      const a = index.get(edge.source);
      const b = index.get(edge.target);
      return a === undefined || b === undefined
        ? []
        : [`${a}:${b}`, `${b}:${a}`];
    })
  );
  const bones = skeleton(
    inside.map((node) => positions.get(node.id) as Point),
    (a, b) => linked.has(`${a}:${b}`)
  );
  const perimeter = perimeterContour(inside.map(box), bones, outside.map(box));

  const labels: FlowLabel[] = [];
  for (const zone of ["inbound"] as const) {
    const members = nodes.filter((node) => zones.get(node.id) === zone);
    if (!members.length) continue;
    const xs = members.map((node) => (positions.get(node.id) as Point).x);
    const tops = members.map(
      (node) =>
        (positions.get(node.id) as Point).y - (sizes.get(node.id) ?? 0) / 2
    );
    labels.push({
      zone,
      x: xs.reduce((sum, value) => sum + value, 0) / xs.length,
      y: Math.min(...tops) - 30,
      count: members.length,
    });
  }

  return {
    positions,
    routes,
    zones,
    perimeter,
    insideCount: inside.length,
    labels,
  };
}

/**
 * A route as cytoscape's segment edges describe it: for each bend, how far
 * along the source→target line it falls and how far off that line, measured
 * between node centres (`edge-distances: node-position`).
 */
export function segmentsFor(source: Point, target: Point, route: Point[]) {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const length = Math.hypot(dx, dy);
  if (!route.length || length < 1) return null;
  const weights: number[] = [];
  const distances: number[] = [];
  for (const point of route) {
    const px = point.x - source.x;
    const py = point.y - source.y;
    weights.push((px * dx + py * dy) / (length * length));
    distances.push((px * -dy + py * dx) / length);
  }
  return {
    weights: weights.map((value) => value.toFixed(4)).join(" "),
    distances: distances.map((value) => value.toFixed(2)).join(" "),
  };
}
