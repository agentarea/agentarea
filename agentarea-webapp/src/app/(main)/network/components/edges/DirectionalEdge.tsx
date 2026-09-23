"use client";

import {
  BaseEdge,
  EdgeLabelRenderer,
  type Edge,
  type EdgeProps,
} from "@xyflow/react";

export type DirectionalEdgeData = Record<string, unknown> & {
  points: { x: number; y: number }[];
  labelPosition: { x: number; y: number };
};

function roundedPath(points: { x: number; y: number }[]) {
  if (!points.length) return "";
  const unique = points.filter(
    (point, index) =>
      index === 0 ||
      point.x !== points[index - 1].x ||
      point.y !== points[index - 1].y
  );
  let path = `M ${unique[0].x} ${unique[0].y}`;
  for (let i = 1; i < unique.length - 1; i++) {
    const previous = unique[i - 1],
      point = unique[i],
      next = unique[i + 1];
    const before = Math.hypot(point.x - previous.x, point.y - previous.y);
    const after = Math.hypot(next.x - point.x, next.y - point.y);
    const radius = Math.min(10, before / 2, after / 2);
    const entry = {
      x: point.x + ((previous.x - point.x) * radius) / before,
      y: point.y + ((previous.y - point.y) * radius) / before,
    };
    const exit = {
      x: point.x + ((next.x - point.x) * radius) / after,
      y: point.y + ((next.y - point.y) * radius) / after,
    };
    path += ` L ${entry.x} ${entry.y} Q ${point.x} ${point.y} ${exit.x} ${exit.y}`;
  }
  const last = unique[unique.length - 1];
  return `${path} L ${last.x} ${last.y}`;
}

export default function DirectionalEdge({
  id,
  data,
  style,
  markerEnd,
  label,
}: EdgeProps<Edge<DirectionalEdgeData>>) {
  if (!data) return null;
  return (
    <>
      <BaseEdge
        id={id}
        path={roundedPath(data.points)}
        style={style}
        markerEnd={markerEnd}
      />
      {label && (
        <EdgeLabelRenderer>
          <span
            className="pointer-events-none absolute rounded bg-background px-1.5 py-1 text-[11px] text-foreground"
            style={{
              transform: `translate(-50%, -100%) translate(${data.labelPosition.x}px, ${data.labelPosition.y}px)`,
            }}
          >
            {label}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
