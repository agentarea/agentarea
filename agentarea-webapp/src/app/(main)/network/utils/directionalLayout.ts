import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import { getNetworkScope } from "./networkConnections";

type PositionedNode = NetworkNodeData & { position: { x: number; y: number } };
type Region = {
  id: string;
  kind:
    | "inputs"
    | "agents"
    | "outputs"
    | "agentCluster"
    | "private"
    | "egress"
    | "unknown";
  position: { x: number; y: number };
  width: number;
  height: number;
  count: number;
  label?: string;
};

const HEADER = 64;
const PADDING = 24;
const GAP = 40;
const LANE_GAP = 64;
const HEIGHT = 104;
const AGENT_WIDTH = 288;
const RESOURCE_WIDTH = 240;

function compareText(a: string, b: string) {
  return a < b ? -1 : a > b ? 1 : 0;
}

function compareNodes(a: NetworkNodeData, b: NetworkNodeData) {
  return compareText(a.label, b.label) || compareText(a.id, b.id);
}

function gridSize(count: number, width: number, columns: number) {
  const rows = Math.max(1, Math.ceil(count / columns));
  return {
    width: columns * width + (columns - 1) * GAP + 2 * PADDING,
    height: HEADER + rows * HEIGHT + (rows - 1) * GAP + PADDING,
  };
}

export function buildDirectionalLayout(topology: TopologyResponse): {
  nodes: PositionedNode[];
  edges: NetworkEdgeData[];
  regions: Region[];
} {
  const originalNodes = [...topology.nodes].sort(compareNodes);
  const byId = new Map<string, NetworkNodeData>();
  for (const node of originalNodes) {
    if (!byId.has(node.id)) byId.set(node.id, node);
  }
  const uniqueNodes = [...byId.values()];
  const edgeIds = new Set<string>();
  const edges = topology.edges
    .filter(
      (edge) =>
        byId.has(edge.source) &&
        byId.has(edge.target) &&
        edge.source !== edge.target
    )
    .map((edge) =>
      edge.relation === "has_trigger"
        ? { ...edge, source: edge.target, target: edge.source }
        : { ...edge }
    )
    .sort(
      (a, b) =>
        compareText(a.source, b.source) ||
        compareText(a.target, b.target) ||
        compareText(a.relation, b.relation) ||
        compareText(a.id, b.id)
    )
    .filter((edge) => {
      if (edgeIds.has(edge.id)) return false;
      edgeIds.add(edge.id);
      return true;
    });

  const agents = uniqueNodes.filter((node) => node.type === "agent");
  const inputs = uniqueNodes.filter((node) => node.type === "trigger");
  const outputs = uniqueNodes.filter(
    (node) => node.type !== "agent" && node.type !== "trigger"
  );
  const adjacency = new Map(agents.map((node) => [node.id, new Set<string>()]));
  const outgoing = new Map(agents.map((node) => [node.id, new Set<string>()]));
  const incoming = new Map(agents.map((node) => [node.id, new Set<string>()]));
  for (const edge of edges) {
    if (
      edge.relation !== "delegates_to" ||
      !adjacency.has(edge.source) ||
      !adjacency.has(edge.target)
    )
      continue;
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
    outgoing.get(edge.source)?.add(edge.target);
    incoming.get(edge.target)?.add(edge.source);
  }

  const visited = new Set<string>();
  const clusters: {
    nodes: NetworkNodeData[];
    rows: NetworkNodeData[][];
    label?: string;
    columns: number;
    width: number;
    height: number;
  }[] = [];
  for (const agent of agents) {
    if (visited.has(agent.id)) continue;
    const pending = [agent.id];
    const members: NetworkNodeData[] = [];
    while (pending.length) {
      const id = pending.pop();
      if (id === undefined || visited.has(id)) continue;
      const member = byId.get(id);
      if (!member) continue;
      visited.add(id);
      members.push(member);
      pending.push(...(adjacency.get(id) ?? []));
    }
    members.sort(compareNodes);
    const roots = members.filter((node) => incoming.get(node.id)?.size === 0);
    const rows: NetworkNodeData[][] = [];
    const emitted = new Set<string>();
    const remainingParents = new Map(
      members.map((node) => [node.id, incoming.get(node.id)?.size ?? 0])
    );
    // Every acyclic rank starts below all of its parents, even when a wide
    // rank spans several rows. Remaining cycles use deterministic fallback rows.
    while (emitted.size < members.length) {
      const remaining = members.filter((node) => !emitted.has(node.id));
      const rank = remaining.filter(
        (node) => remainingParents.get(node.id) === 0
      );
      const batch = rank.length ? rank : remaining;
      for (let index = 0; index < batch.length; index += 2) {
        rows.push(batch.slice(index, index + 2));
      }
      for (const member of batch) {
        emitted.add(member.id);
        for (const child of outgoing.get(member.id) ?? []) {
          remainingParents.set(child, (remainingParents.get(child) ?? 0) - 1);
        }
      }
    }
    const ordered = rows.flat();
    const columns = Math.max(...rows.map((row) => row.length));
    clusters.push({
      nodes: ordered,
      rows,
      ...(roots.length === 1 ? { label: roots[0].label } : {}),
      columns,
      ...gridSize(rows.length * columns, AGENT_WIDTH, columns),
    });
  }
  const triggeredAgents = new Set(
    edges
      .filter((edge) => byId.get(edge.source)?.type === "trigger")
      .map((edge) => edge.target)
  );
  clusters.sort(
    (a, b) =>
      Number(b.nodes.some((node) => triggeredAgents.has(node.id))) -
        Number(a.nodes.some((node) => triggeredAgents.has(node.id))) ||
      b.nodes.length - a.nodes.length ||
      compareNodes(a.nodes[0], b.nodes[0])
  );

  const groups = (["private", "egress", "unknown"] as const)
    .map((scope) => {
      const nodes = outputs.filter((node) => getNetworkScope(node) === scope);
      const columns = nodes.length >= 2 ? 2 : 1;
      return {
        scope,
        nodes,
        columns,
        ...gridSize(nodes.length, RESOURCE_WIDTH, columns),
      };
    })
    .filter((group) => group.nodes.length > 0);

  const inputSize = gridSize(inputs.length, RESOURCE_WIDTH, 1);
  const agentWidth =
    Math.max(
      AGENT_WIDTH + 2 * PADDING,
      ...clusters.map((cluster) => cluster.width)
    ) +
    2 * PADDING;
  const outputWidth =
    Math.max(
      RESOURCE_WIDTH + 2 * PADDING,
      ...groups.map((group) => group.width)
    ) +
    2 * PADDING;
  const agentX = inputSize.width + LANE_GAP;
  const outputX = agentX + agentWidth + LANE_GAP;
  const regions: Region[] = [];
  const nodes: PositionedNode[] = [];
  const reservedIds = new Set([...byId.keys(), ...edgeIds]);
  const regionId = (key: string) => {
    let id = `__network_region__:${key}`;
    while (reservedIds.has(id)) id += ":region";
    reservedIds.add(id);
    return id;
  };
  const placeNodes = (
    items: NetworkNodeData[],
    x: number,
    y: number,
    width: number,
    columns: number
  ) => {
    items.forEach((node, index) =>
      nodes.push({
        ...node,
        position: {
          x: x + PADDING + (index % columns) * (width + GAP),
          y: y + HEADER + Math.floor(index / columns) * (HEIGHT + GAP),
        },
      })
    );
  };
  const inputRegion: Region = {
    id: regionId("inputs"),
    kind: "inputs",
    position: { x: 0, y: 0 },
    ...inputSize,
    count: inputs.length,
  };
  const agentRegion: Region = {
    id: regionId("agents"),
    kind: "agents",
    position: { x: agentX, y: 0 },
    width: agentWidth,
    height: inputSize.height,
    count: agents.length,
  };
  const outputRegion: Region = {
    id: regionId("outputs"),
    kind: "outputs",
    position: { x: outputX, y: 0 },
    width: outputWidth,
    height: inputSize.height,
    count: outputs.length,
  };
  regions.push(inputRegion, agentRegion, outputRegion);

  let clusterY = HEADER;
  for (const cluster of clusters) {
    const x = agentX + PADDING;
    regions.push({
      id: regionId(
        `agents:${cluster.nodes
          .map((node) => encodeURIComponent(node.id))
          .sort(compareText)
          .join(";")}`
      ),
      kind: "agentCluster",
      position: { x, y: clusterY },
      width: cluster.width,
      height: cluster.height,
      count: cluster.nodes.length,
      ...(cluster.label !== undefined ? { label: cluster.label } : {}),
    });
    cluster.rows.forEach((row, rowIndex) => {
      row.forEach((node, columnIndex) =>
        nodes.push({
          ...node,
          position: {
            x:
              x +
              PADDING +
              ((cluster.columns - row.length) * (AGENT_WIDTH + GAP)) / 2 +
              columnIndex * (AGENT_WIDTH + GAP),
            y: clusterY + HEADER + rowIndex * (HEIGHT + GAP),
          },
        })
      );
    });
    clusterY += cluster.height + GAP;
  }
  const positionedAgents = new Map(nodes.map((node) => [node.id, node]));
  const desiredInputY = (input: NetworkNodeData) => {
    const targets = edges
      .filter((edge) => edge.source === input.id)
      .map((edge) => positionedAgents.get(edge.target)?.position.y)
      .filter((y): y is number => y !== undefined);
    return targets.length ? Math.min(...targets) : HEADER;
  };
  let nextInputY = HEADER;
  for (const input of [...inputs].sort(
    (a, b) => desiredInputY(a) - desiredInputY(b) || compareNodes(a, b)
  )) {
    const y = Math.max(nextInputY, desiredInputY(input));
    nodes.push({ ...input, position: { x: PADDING, y } });
    nextInputY = y + HEIGHT + GAP;
  }
  if (inputs.length) inputRegion.height = nextInputY - GAP + PADDING;
  let groupY = HEADER;
  for (const group of groups) {
    const x = outputX + PADDING;
    regions.push({
      id: regionId(`outputs:${group.scope}`),
      kind: group.scope,
      position: { x, y: groupY },
      width: group.width,
      height: group.height,
      count: group.nodes.length,
    });
    placeNodes(group.nodes, x, groupY, RESOURCE_WIDTH, group.columns);
    groupY += group.height + GAP;
  }
  agentRegion.height = clusters.length
    ? clusterY - GAP + PADDING
    : gridSize(0, AGENT_WIDTH, 1).height;
  outputRegion.height = groups.length
    ? groupY - GAP + PADDING
    : gridSize(0, RESOURCE_WIDTH, 1).height;
  return { nodes, edges, regions };
}
