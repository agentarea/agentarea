"use client";

import { getBezierPath, type EdgeProps } from "@xyflow/react";

export default function DataFlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    curvature: 0.35,
  });

  const isInactive = data?.isInactive as boolean | undefined;
  const dimmed = data?.dimmed as boolean | undefined;
  const highlighted = data?.highlighted as boolean | undefined;

  let stroke = "#a1a1aa";
  let strokeWidth = 1.25;
  let opacity = 0.55;

  if (highlighted) {
    stroke = "#2563eb";
    strokeWidth = 2;
    opacity = 1;
  } else if (dimmed) {
    stroke = "#d4d4d8";
    strokeWidth = 1;
    opacity = 0.18;
  }

  const strokeDasharray = isInactive ? "5,5" : undefined;

  return (
    <>
      <defs>
        <marker
          id={`arrow-${id}`}
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto"
        >
          <path d="M0,0 L0,6 L6,3 z" fill={stroke} opacity={opacity} />
        </marker>
      </defs>
      <path
        id={id}
        d={edgePath}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeOpacity={opacity}
        strokeDasharray={strokeDasharray}
        markerEnd={`url(#arrow-${id})`}
      />
    </>
  );
}
