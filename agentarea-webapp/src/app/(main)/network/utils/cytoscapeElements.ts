import type cytoscape from "cytoscape";
import type {
  CanvasEdge,
  CanvasNode,
  CanvasPoint,
} from "../components/networkCanvasTypes";

function center(node: CanvasNode): CanvasPoint {
  return {
    x: node.position.x + node.width / 2,
    y: node.position.y + node.height / 2,
  };
}

function distinctPoints(points: CanvasPoint[]): CanvasPoint[] {
  return points
    .filter(
      (point, index) =>
        index === 0 ||
        point.x !== points[index - 1].x ||
        point.y !== points[index - 1].y
    )
    .map(({ x, y }) => ({ x, y }));
}

function personOffset(node: CanvasNode): number {
  const people = Array.isArray(node.data.people) ? node.data.people : [];
  const selected = people.findIndex(
    (person: unknown) =>
      typeof person === "object" &&
      person !== null &&
      "user_id" in person &&
      person.user_id === node.data.selectedId
  );
  return selected < 0 ? node.height / 2 : 70 + Math.min(selected, 3) * 44;
}

/** Return the same model-space points used by the graph and its HTML labels. */
export function getEdgePoints(
  edge: CanvasEdge,
  nodes: CanvasNode[]
): CanvasPoint[] {
  const source = nodes.find(({ id }) => id === edge.source);
  const target = nodes.find(({ id }) => id === edge.target);
  if (!source || !target || source.id === target.id) return [];
  if (edge.data.points && edge.data.points.length >= 2) {
    return distinctPoints(edge.data.points);
  }

  const horizontal = source.data._horizontal !== false;
  const sourceCenter = center(source);
  const targetCenter = center(target);
  const fromRight = horizontal || source.type === "people";
  const start = fromRight
    ? {
        x: source.position.x + source.width,
        y:
          source.position.y +
          (source.type === "people" ? personOffset(source) : source.height / 2),
      }
    : { x: sourceCenter.x, y: source.position.y + source.height };
  const end = horizontal
    ? { x: target.position.x, y: targetCenter.y }
    : { x: targetCenter.x, y: target.position.y };
  const clearance = 24;

  if (horizontal) {
    if (end.x >= start.x + clearance * 2) {
      const middleX = (start.x + end.x) / 2;
      return distinctPoints([
        start,
        { x: middleX, y: start.y },
        { x: middleX, y: end.y },
        end,
      ]);
    }
    const below =
      Math.max(
        source.position.y + source.height,
        target.position.y + target.height
      ) + clearance;
    return distinctPoints([
      start,
      { x: start.x + clearance, y: start.y },
      { x: start.x + clearance, y: below },
      { x: end.x - clearance, y: below },
      { x: end.x - clearance, y: end.y },
      end,
    ]);
  }

  if (source.type === "people") {
    return distinctPoints([
      start,
      { x: start.x + clearance, y: start.y },
      { x: start.x + clearance, y: end.y - clearance },
      { x: end.x, y: end.y - clearance },
      end,
    ]);
  }
  if (end.y >= start.y + clearance * 2) {
    const middleY = (start.y + end.y) / 2;
    return distinctPoints([
      start,
      { x: start.x, y: middleY },
      { x: end.x, y: middleY },
      end,
    ]);
  }
  const right =
    Math.max(
      source.position.x + source.width,
      target.position.x + target.width
    ) + clearance;
  return distinctPoints([
    start,
    { x: start.x, y: start.y + clearance },
    { x: right, y: start.y + clearance },
    { x: right, y: end.y - clearance },
    { x: end.x, y: end.y - clearance },
    end,
  ]);
}

/** Convert absolute bends for Cytoscape's edge-distances: node-position. */
export function getSegmentCoordinates(
  source: CanvasPoint,
  target: CanvasPoint,
  bends: CanvasPoint[]
): { weights: number[]; distances: number[] } {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const length = Math.hypot(dx, dy);
  if (length === 0) return { weights: [], distances: [] };
  return {
    weights: bends.map(
      (point) =>
        ((point.x - source.x) * dx + (point.y - source.y) * dy) /
        (length * length)
    ),
    distances: bends.map(
      (point) =>
        ((point.x - source.x) * -dy + (point.y - source.y) * dx) / length
    ),
  };
}

function endpoint(point: CanvasPoint, origin: CanvasPoint): string {
  return `${point.x - origin.x}px ${point.y - origin.y}px`;
}

export function buildCytoscapeElements(
  nodes: CanvasNode[],
  edges: CanvasEdge[]
): cytoscape.ElementDefinition[] {
  const byId = new Map<string, CanvasNode>();
  for (const node of nodes) {
    if (!byId.has(node.id)) byId.set(node.id, node);
  }
  const elements: cytoscape.ElementDefinition[] = [...byId.values()].map(
    (node) => ({
      group: "nodes",
      data: {
        id: `n:${node.id}`,
        originalId: node.id,
        nodeType: node.type,
        width: node.width,
        height: node.height,
      },
      position: center(node),
      classes: node.type,
      grabbable: false,
      selectable: false,
    })
  );
  const edgeIds = new Set<string>();
  for (const edge of edges) {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (!source || !target || source.id === target.id || edgeIds.has(edge.id))
      continue;
    const points = getEdgePoints(edge, [source, target]);
    if (points.length < 2) continue;
    const sourceCenter = center(source);
    const targetCenter = center(target);
    const coordinates = getSegmentCoordinates(
      sourceCenter,
      targetCenter,
      points.slice(1, -1)
    );
    edgeIds.add(edge.id);
    elements.push({
      group: "edges",
      data: {
        id: `e:${edge.id}`,
        originalId: edge.id,
        source: `n:${source.id}`,
        target: `n:${target.id}`,
        points,
        ...coordinates,
        sourceEndpoint: endpoint(points[0], sourceCenter),
        targetEndpoint: endpoint(points[points.length - 1], targetCenter),
        curveStyle: coordinates.weights.length ? "round-segments" : "straight",
        stroke: edge.style.stroke ?? "currentColor",
        width: Number(edge.style.strokeWidth ?? 1.5),
        opacity: Number(edge.style.opacity ?? 1),
        dashed: Boolean(
          edge.style.strokeDasharray && edge.style.strokeDasharray !== "none"
        ),
        selected: edge.selected ?? false,
        relation: edge.data.relation,
        label: edge.label ?? "",
        ariaLabel: edge.ariaLabel ?? "",
        labelPosition: edge.data.labelPosition,
      },
      classes: edge.selected ? "selected" : "",
      selectable: false,
    });
  }
  return elements;
}

export function getCanvasBounds(
  nodes: CanvasNode[],
  focusIds?: string[] | null
): { x: number; y: number; width: number; height: number } {
  const ids = focusIds?.length ? new Set(focusIds) : null;
  const focused = ids
    ? nodes.filter((node) => node.type !== "region" && ids.has(node.id))
    : nodes;
  const fitting = focused.length ? focused : nodes;
  if (!fitting.length) return { x: 0, y: 0, width: 1, height: 1 };
  const x = Math.min(...fitting.map((node) => node.position.x));
  const y = Math.min(...fitting.map((node) => node.position.y));
  return {
    x,
    y,
    width: Math.max(...fitting.map((node) => node.position.x + node.width)) - x,
    height:
      Math.max(...fitting.map((node) => node.position.y + node.height)) - y,
  };
}
