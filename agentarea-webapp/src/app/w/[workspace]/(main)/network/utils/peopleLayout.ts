import type { buildDirectionalLayout } from "./directionalLayout";

type Layout = ReturnType<typeof buildDirectionalLayout>;
type Point = { x: number; y: number };

export function withPeopleRoster(
  layout: Layout,
  rosterHeight: number
): Layout & { peoplePosition: Point; peopleWidth: 240 } {
  const inputLane = layout.regions.find(({ kind }) => kind === "inputs");
  if (!inputLane) throw new Error("People roster requires an input lane");

  const peoplePosition = {
    x: inputLane.position.x + 24,
    y: inputLane.position.y + 64,
  };
  const rosterBottom = peoplePosition.y + rosterHeight;
  let nextY = rosterBottom + 32;
  const movedTriggers = new Map<string, Layout["nodes"][number]>();
  const triggers = layout.nodes
    .filter(({ type }) => type === "trigger")
    .sort(
      (a, b) =>
        a.position.y - b.position.y || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
    );
  let contentBottom = rosterBottom;
  for (const trigger of triggers) {
    const y = Math.max(trigger.position.y, nextY);
    movedTriggers.set(
      trigger.id,
      y === trigger.position.y
        ? trigger
        : { ...trigger, position: { ...trigger.position, y } }
    );
    contentBottom = y + 104;
    nextY = y + 144;
  }

  return {
    ...layout,
    nodes: layout.nodes.map((node) => movedTriggers.get(node.id) ?? node),
    regions: layout.regions.map((region) =>
      region === inputLane
        ? {
            ...region,
            height: Math.max(
              region.height,
              contentBottom - region.position.y + 24
            ),
          }
        : region
    ),
    peoplePosition,
    peopleWidth: 240,
  };
}

export function getPersonRoute(
  source: { position: Point; sourceOffset: number; sourceId: string },
  targetAgent: Layout["nodes"][number],
  layout: Layout
): {
  points: Point[];
  sourceHandle: string;
  targetHandle: "flow-target" | "delegation-target";
  label: Point;
} {
  const inputLane = layout.regions.find(({ kind }) => kind === "inputs");
  const agentLane = layout.regions.find(({ kind }) => kind === "agents");
  if (!inputLane || !agentLane)
    throw new Error("People routes require input and agent lanes");

  const start = {
    x: source.position.x + 240,
    y: source.position.y + source.sourceOffset,
  };
  const corridorX =
    (inputLane.position.x + inputLane.width + agentLane.position.x) / 2;
  const targetLeft = {
    x: targetAgent.position.x,
    y: targetAgent.position.y + 52,
  };
  const blocked = layout.nodes.some((node) => {
    if (node.id === targetAgent.id) return false;
    return (
      targetLeft.y >= node.position.y &&
      targetLeft.y <= node.position.y + 104 &&
      Math.max(Math.min(corridorX, targetLeft.x), node.position.x) <
        Math.min(
          Math.max(corridorX, targetLeft.x),
          node.position.x + (node.type === "agent" ? 288 : 240)
        )
    );
  });
  const endpoint = blocked
    ? { x: targetAgent.position.x + 144, y: targetAgent.position.y }
    : targetLeft;
  const approachY = blocked ? endpoint.y - 16 : endpoint.y;
  const points = [
    start,
    { x: corridorX, y: start.y },
    { x: corridorX, y: approachY },
    { x: endpoint.x, y: approachY },
    ...(blocked ? [endpoint] : []),
  ].filter(
    (point, index, all) =>
      index === 0 ||
      point.x !== all[index - 1].x ||
      point.y !== all[index - 1].y
  );

  return {
    points,
    sourceHandle: source.sourceId,
    targetHandle: blocked ? "delegation-target" : "flow-target",
    label: { x: (corridorX + endpoint.x) / 2, y: approachY },
  };
}
