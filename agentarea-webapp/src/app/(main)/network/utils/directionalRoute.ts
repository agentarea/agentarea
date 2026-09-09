import type { NetworkEdgeData } from "../types";
import type { buildDirectionalLayout } from "./directionalLayout";
import { getNetworkScope } from "./networkConnections";

type Layout = ReturnType<typeof buildDirectionalLayout>;
type Point = { x: number; y: number };
type Route = {
  points: Point[];
  sourceHandle?: string;
  targetHandle?: string;
  label: Point;
};

const CARD_HEIGHT = 104;
const CLEARANCE = 16;

function width(node: Layout["nodes"][number]) {
  return node.type === "agent" ? 288 : 240;
}

function finishRoute(
  points: Point[],
  handles: Pick<Route, "sourceHandle" | "targetHandle">,
  labelOverride?: Point
): Route {
  const distinct = points.filter(
    (point, index) =>
      index === 0 ||
      point.x !== points[index - 1].x ||
      point.y !== points[index - 1].y
  );
  let label = distinct[0] ?? { x: 0, y: 0 };
  let longest = 0;
  for (let index = 1; index < distinct.length; index++) {
    const previous = distinct[index - 1];
    const current = distinct[index];
    const distance = Math.abs(current.x - previous.x);
    if (previous.y === current.y && distance > longest) {
      longest = distance;
      label = { x: (previous.x + current.x) / 2, y: current.y };
    }
  }
  return { points: distinct, ...handles, label: labelOverride ?? label };
}

export function getDirectionalRoute(
  edge: NetworkEdgeData,
  nodes: Layout["nodes"],
  regions: Layout["regions"]
): Route {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  if (!source || !target || source.id === target.id) {
    return { points: [], label: { x: 0, y: 0 } };
  }

  const agentLane = regions.find(({ kind }) => kind === "agents");
  const inputLane = regions.find(({ kind }) => kind === "inputs");
  const workspace = regions.find(({ kind }) => kind === "workspace");
  const egress = regions.find(({ kind }) => kind === "egress");
  const privateRegion = regions.find(({ kind }) => kind === "private");
  const targetTop = {
    x: target.position.x + width(target) / 2,
    y: target.position.y,
  };
  const approachY = targetTop.y - CLEARANCE;
  const sourceRight = {
    x: source.position.x + width(source),
    y: source.position.y + CARD_HEIGHT / 2,
  };
  const sourceBottomY = source.position.y + CARD_HEIGHT;
  const targetHandle =
    target.type === "agent" ? "delegation-target" : undefined;

  if (source.type === "agent" && target.type === "agent") {
    const cluster = regions.find(
      (region) =>
        region.kind === "agentCluster" &&
        source.position.x >= region.position.x &&
        source.position.x + width(source) <= region.position.x + region.width &&
        source.position.y >= region.position.y &&
        sourceBottomY <= region.position.y + region.height
    );
    const corridorX =
      (cluster?.position.x ??
        agentLane?.position.x ??
        Math.min(source.position.x, target.position.x) - 24) + 12;
    const start = {
      x: source.position.x + width(source) / 2,
      y: sourceBottomY,
    };
    return finishRoute(
      [
        start,
        { x: start.x, y: sourceBottomY + CLEARANCE },
        { x: corridorX, y: sourceBottomY + CLEARANCE },
        { x: corridorX, y: approachY },
        { x: targetTop.x, y: approachY },
        targetTop,
      ],
      { sourceHandle: "delegation-source", targetHandle }
    );
  }

  if (source.type === "trigger" && target.type === "agent") {
    const corridorX =
      inputLane && agentLane
        ? (inputLane.position.x + inputLane.width + agentLane.position.x) / 2
        : (sourceRight.x + target.position.x) / 2;
    const targetLeft = {
      x: target.position.x,
      y: target.position.y + CARD_HEIGHT / 2,
    };
    const leftApproachBlocked = nodes.some((node) => {
      if (node.id === source.id || node.id === target.id) return false;
      return (
        targetLeft.y >= node.position.y &&
        targetLeft.y <= node.position.y + CARD_HEIGHT &&
        Math.max(Math.min(corridorX, targetLeft.x), node.position.x) <
          Math.min(
            Math.max(corridorX, targetLeft.x),
            node.position.x + width(node)
          )
      );
    });
    if (!leftApproachBlocked) {
      return finishRoute(
        [
          sourceRight,
          { x: corridorX, y: sourceRight.y },
          { x: corridorX, y: targetLeft.y },
          targetLeft,
        ],
        { targetHandle: "flow-target" }
      );
    }
    return finishRoute(
      [
        sourceRight,
        { x: corridorX, y: sourceRight.y },
        { x: corridorX, y: approachY },
        { x: targetTop.x, y: approachY },
        targetTop,
      ],
      { targetHandle }
    );
  }

  const workspaceRight = workspace
    ? workspace.position.x + workspace.width
    : (agentLane?.position.x ?? source.position.x) +
      (agentLane?.width ?? width(source)) +
      32;
  const internalCorridor =
    agentLane && privateRegion
      ? (agentLane.position.x + agentLane.width + privateRegion.position.x) / 2
      : workspaceRight - 12;
  const outsideCorridor = egress
    ? (workspaceRight + egress.position.x) / 2
    : workspaceRight + 32;
  const sourceInside =
    source.type === "agent" || getNetworkScope(source) === "private";
  const targetInside =
    target.type === "agent" || getNetworkScope(target) === "private";
  const corridorX = targetInside ? internalCorridor : outsideCorridor;
  const crossings: Point[] = [];
  // The two internal groups have independent rows. Cross the resource column
  // below its last card instead of drawing through it at an agent's row gap.
  const bridgeY = privateRegion
    ? privateRegion.position.y + privateRegion.height + CLEARANCE
    : sourceBottomY + CLEARANCE;
  if (source.type === "agent" && !targetInside) {
    crossings.push(
      { x: internalCorridor, y: sourceBottomY + CLEARANCE },
      { x: internalCorridor, y: bridgeY },
      { x: outsideCorridor, y: bridgeY }
    );
  } else if (!sourceInside && targetInside) {
    crossings.push(
      { x: outsideCorridor, y: sourceBottomY + CLEARANCE },
      { x: outsideCorridor, y: bridgeY },
      { x: internalCorridor, y: bridgeY }
    );
  } else {
    crossings.push({ x: corridorX, y: sourceBottomY + CLEARANCE });
  }
  return finishRoute(
    [
      sourceRight,
      { x: sourceRight.x + CLEARANCE, y: sourceRight.y },
      { x: sourceRight.x + CLEARANCE, y: sourceBottomY + CLEARANCE },
      ...crossings,
      { x: corridorX, y: approachY },
      { x: targetTop.x, y: approachY },
      targetTop,
    ],
    {
      ...(source.type === "agent" ? { sourceHandle: "flow-source" } : {}),
      ...(targetHandle ? { targetHandle } : {}),
    },
    { x: corridorX, y: approachY }
  );
}
