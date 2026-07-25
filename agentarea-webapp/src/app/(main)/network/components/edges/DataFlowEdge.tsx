"use client";

import { getBezierPath, type EdgeProps } from "@xyflow/react";

const RELATION_COLORS: Record<string, string> = {
  has_trigger: "#2563eb",
  uses_mcp: "#64748b",
  uses_openapi: "#64748b",
  has_skill: "#7c3aed",
  delegates_to: "#0ea5e9",
};

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
    curvature: 0.45,
  });

  const isInactive = data?.isInactive as boolean | undefined;
  const dimmed = data?.dimmed as boolean | undefined;
  const highlighted = data?.highlighted as boolean | undefined;
  const relation = (data?.relation as string | undefined) ?? "";

  const baseColor = RELATION_COLORS[relation] ?? "#94a3b8";

  let stroke = baseColor;
  let strokeWidth = 1.6;
  let opacity = 0.78;

  if (highlighted) {
    stroke = "#2563eb";
    strokeWidth = 2.4;
    opacity = 1;
  } else if (dimmed) {
    stroke = "#cbd5e1";
    strokeWidth = 1;
    opacity = 0.2;
  }

  const strokeDasharray =
    isInactive || relation === "uses_openapi" || relation === "has_skill"
      ? "5,5"
      : undefined;

  return (
    <>
      <path
        d={edgePath}
        fill="none"
        stroke="#ffffff"
        strokeWidth={strokeWidth + 3}
        strokeOpacity={dimmed ? 0.08 : 0.7}
      />
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
