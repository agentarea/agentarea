import type { AccessControlGraph, AccessControlNode } from "@/types/access-control";

// Layout constants tuned to match the design prototype's node/edge styling.
export const NODE_WIDTH = 168;
export const NODE_HEIGHT = 46;
const COLUMN_GAP = 152; // horizontal gap between columns
const ROW_GAP = 30; // vertical gap between nodes in a column
const TOP_PADDING = 36; // space for column labels
const SIDE_PADDING = 12;

export interface PositionedNode extends AccessControlNode {
  x: number;
  y: number;
  w: number;
  h: number;
  column: number;
}

export interface PositionedEdge {
  from: string;
  to: string;
  relation: string;
  path: string;
  labelX: number;
  labelY: number;
}

export interface GraphLayout {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
  columnLabels: { label: string; x: number }[];
}

// Column 1 = agents, column 2 = collections + mcp resources.
function columnForKind(kind: AccessControlNode["kind"]): number {
  return kind === "agent" ? 0 : 1;
}

export function layoutGraph(graph: AccessControlGraph): GraphLayout {
  const columns: AccessControlNode[][] = [[], []];
  for (const node of graph.nodes) {
    columns[columnForKind(node.kind)].push(node);
  }

  const positioned = new Map<string, PositionedNode>();
  let maxBottom = 0;

  columns.forEach((colNodes, columnIndex) => {
    const x = SIDE_PADDING + columnIndex * (NODE_WIDTH + COLUMN_GAP);
    colNodes.forEach((node, rowIndex) => {
      const y = TOP_PADDING + rowIndex * (NODE_HEIGHT + ROW_GAP);
      positioned.set(node.id, {
        ...node,
        x,
        y,
        w: NODE_WIDTH,
        h: NODE_HEIGHT,
        column: columnIndex,
      });
      maxBottom = Math.max(maxBottom, y + NODE_HEIGHT);
    });
  });

  const edges: PositionedEdge[] = [];
  for (const edge of graph.edges) {
    const from = positioned.get(edge.from);
    const to = positioned.get(edge.to);
    if (!from || !to) continue;

    const a = { x: from.x + from.w, y: from.y + from.h / 2 };
    const b = { x: to.x, y: to.y + to.h / 2 };
    const dx = Math.max(40, (b.x - a.x) / 2);
    const path = `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
    edges.push({
      from: edge.from,
      to: edge.to,
      relation: edge.relation,
      path,
      labelX: (a.x + b.x) / 2,
      labelY: (a.y + b.y) / 2,
    });
  }

  const width = SIDE_PADDING * 2 + 2 * NODE_WIDTH + COLUMN_GAP;
  const height = Math.max(maxBottom + TOP_PADDING, 320);

  const columnLabels = [
    { label: "Agents", x: SIDE_PADDING },
    { label: "Collections", x: SIDE_PADDING + NODE_WIDTH + COLUMN_GAP },
  ];

  return {
    nodes: Array.from(positioned.values()),
    edges,
    width,
    height,
    columnLabels,
  };
}

export function formatCount(count: number | null): string | null {
  if (count == null) return null;
  if (count > 9999) return `${Math.round(count / 1000)}k`;
  if (count > 999) return `${(count / 1000).toFixed(1)}k`;
  return String(count);
}

// Map a relation to its edge color class (matches prototype tokens via globals).
export const RELATION_VERB: Record<string, string> = {
  user: "use",
  editor: "configure",
  owner: "manage",
  connect: "connect",
  member: "join",
};
