import dagre from "@dagrejs/dagre";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";

export const ORG_NODE_WIDTH = 240;
export const ORG_NODE_HEIGHT = 104;

const COMPONENT_GAP = 88;

type PositionedNode = NetworkNodeData & {
  position: { x: number; y: number };
};

function compareText(a: string, b: string) {
  return a < b ? -1 : a > b ? 1 : 0;
}

function compareNodes(a: NetworkNodeData, b: NetworkNodeData) {
  return compareText(a.label, b.label) || compareText(a.id, b.id);
}

export function buildOrgChartLayout(
  topology: TopologyResponse,
  agentsOnly: boolean,
  nodeSize: (node: NetworkNodeData) => {
    width: number;
    height: number;
  } = () => ({
    width: ORG_NODE_WIDTH,
    height: ORG_NODE_HEIGHT,
  }),
  options: { direction?: "TB" | "LR"; aspectRatio?: number } = {}
): { nodes: PositionedNode[]; edges: NetworkEdgeData[] } {
  const nodes = topology.nodes
    .filter((node) => !agentsOnly || node.type === "agent")
    .sort(compareNodes);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = topology.edges
    .filter(
      (edge) =>
        nodeIds.has(edge.source) &&
        nodeIds.has(edge.target) &&
        (!agentsOnly || edge.relation === "delegates_to")
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
    );

  // Lay out each connected group separately so independent agents can wrap.
  const neighbors = new Map(nodes.map((node) => [node.id, new Set<string>()]));
  for (const edge of edges) {
    neighbors.get(edge.source)?.add(edge.target);
    neighbors.get(edge.target)?.add(edge.source);
  }

  const visited = new Set<string>();
  const components: NetworkNodeData[][] = [];
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  for (const node of nodes) {
    if (visited.has(node.id)) continue;
    const pending = [node];
    const component: NetworkNodeData[] = [];
    visited.add(node.id);
    while (pending.length) {
      const current = pending.pop();
      if (!current) continue;
      component.push(current);
      for (const neighbor of neighbors.get(current.id) ?? []) {
        if (visited.has(neighbor)) continue;
        visited.add(neighbor);
        const next = nodesById.get(neighbor);
        if (next) pending.push(next);
      }
    }
    components.push(component.sort(compareNodes));
  }

  const groups = components.map((component) => {
    const graph = new dagre.graphlib.Graph({ multigraph: true });
    graph.setDefaultEdgeLabel(() => ({}));
    graph.setGraph({
      rankdir: options.direction ?? "TB",
      nodesep: 56,
      ranksep: 88,
    });
    for (const node of component) {
      graph.setNode(node.id, nodeSize(node));
    }
    const ids = new Set(component.map((node) => node.id));
    for (const edge of edges) {
      if (ids.has(edge.source)) {
        graph.setEdge(edge.source, edge.target, {}, edge.id);
      }
    }
    dagre.layout(graph);

    const positioned = component.map((node) => {
      const center = graph.node(node.id);
      return {
        ...node,
        position: {
          x: center.x - center.width / 2,
          y: center.y - center.height / 2,
        },
      };
    });
    const minX = Math.min(...positioned.map((node) => node.position.x));
    const minY = Math.min(...positioned.map((node) => node.position.y));
    const width =
      Math.max(
        ...positioned.map((node) => node.position.x + graph.node(node.id).width)
      ) - minX;
    const height =
      Math.max(
        ...positioned.map(
          (node) => node.position.y + graph.node(node.id).height
        )
      ) - minY;
    return { nodes: positioned, minX, minY, width, height };
  });

  // Larger groups lead the rows; label/id ordering breaks ties predictably.
  groups.sort(
    (a, b) =>
      b.nodes.length - a.nodes.length || compareNodes(a.nodes[0], b.nodes[0])
  );
  const area = groups.reduce(
    (sum, group) =>
      sum + (group.width + COMPONENT_GAP) * (group.height + COMPONENT_GAP),
    0
  );
  const rowWidth = Math.max(
    ...groups.map((group) => group.width),
    Math.sqrt(area * (options.aspectRatio ?? 1.6))
  );
  const result: PositionedNode[] = [];
  let x = 0;
  let y = 0;
  let rowHeight = 0;
  for (const group of groups) {
    if (x > 0 && x + group.width > rowWidth) {
      x = 0;
      y += rowHeight + COMPONENT_GAP;
      rowHeight = 0;
    }
    for (const node of group.nodes) {
      result.push({
        ...node,
        position: {
          x: node.position.x - group.minX + x,
          y: node.position.y - group.minY + y,
        },
      });
    }
    x += group.width + COMPONENT_GAP;
    rowHeight = Math.max(rowHeight, group.height);
  }

  return { nodes: result.sort(compareNodes), edges };
}
