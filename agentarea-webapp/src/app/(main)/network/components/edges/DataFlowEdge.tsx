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
  const [edgePath] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const isRisk = data?.isRisk as boolean | undefined;
  const isInactive = data?.isInactive as boolean | undefined;

  const stroke = isRisk ? "#f97316" : "#d4d4d8";
  const strokeWidth = isRisk ? 2 : 1.5;
  const strokeDasharray = isInactive ? "5,5" : undefined;

  const midX = (sourceX + targetX) / 2;
  const midY = (sourceY + targetY) / 2;

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
          <path d="M0,0 L0,6 L6,3 z" fill={stroke} />
        </marker>
      </defs>
      <path
        id={id}
        d={edgePath}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeDasharray={strokeDasharray}
        markerEnd={`url(#arrow-${id})`}
      />
      {isRisk && (
        <text
          x={midX}
          y={midY - 8}
          textAnchor="middle"
          fontSize="11"
          fill="#f97316"
        >
          ⚠
        </text>
      )}
    </>
  );
}
