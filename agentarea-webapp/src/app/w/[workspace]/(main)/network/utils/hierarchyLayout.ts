import dagre from "@dagrejs/dagre";

export interface LayoutNode {
  id: string;
  size: number;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

function compareText(a: string, b: string) {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Layered positions for the delegation (top-down) and access (left-to-right)
 * lenses. Input is sorted first so the same topology always lands the same
 * way, whatever order the API returned it in. Positions are node centres.
 */
export function hierarchyPositions(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  direction: "TB" | "LR"
): Map<string, { x: number; y: number }> {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({
    rankdir: direction,
    nodesep: direction === "TB" ? 48 : 22,
    ranksep: direction === "TB" ? 96 : 180,
    marginx: 0,
    marginy: 0,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  const ids = new Set(nodes.map((node) => node.id));
  for (const node of [...nodes].sort((a, b) => compareText(a.id, b.id))) {
    // Room under each node for its label, which the canvas draws below it.
    graph.setNode(node.id, { width: node.size + 96, height: node.size + 28 });
  }
  for (const edge of [...edges].sort(
    (a, b) => compareText(a.source, b.source) || compareText(a.target, b.target)
  )) {
    if (ids.has(edge.source) && ids.has(edge.target)) {
      graph.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(graph);
  const positions = new Map<string, { x: number; y: number }>();
  for (const id of ids) {
    const { x, y } = graph.node(id);
    positions.set(id, { x, y });
  }
  return positions;
}

/**
 * A shelf of nodes that connect to nothing, laid out row by row under the
 * graph. A force layout packs such nodes edge to edge, which buries their
 * labels; a fixed cell wide enough for a label keeps every one readable.
 */
export function shelfPositions(
  ids: string[],
  origin: { x: number; y: number },
  width: number,
  cell = { width: 150, height: 100 }
): Map<string, { x: number; y: number }> {
  const columns = Math.max(1, Math.floor(width / cell.width));
  return new Map(
    ids.map((id, index) => [
      id,
      {
        x: origin.x + cell.width / 2 + (index % columns) * cell.width,
        y:
          origin.y +
          cell.height / 2 +
          Math.floor(index / columns) * cell.height,
      },
    ])
  );
}
