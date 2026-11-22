"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  Position,
  useInternalNode,
  type Edge,
  type EdgeProps,
  type InternalNode,
} from "@xyflow/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCanvasTiles } from "./CanvasContext";

export type CanvasEdge = Edge<{ label: string }, "floating">;

type Box = { x: number; y: number; width: number; height: number };

function boxOf(node: InternalNode): Box {
  return {
    x: node.internals.positionAbsolute.x,
    y: node.internals.positionAbsolute.y,
    width: node.measured.width ?? node.width ?? 0,
    height: node.measured.height ?? node.height ?? 0,
  };
}

/** Where the line from the centre of `box` towards `to` leaves the box. */
function exitPoint(box: Box, to: Box): { x: number; y: number } {
  const w = box.width / 2;
  const h = box.height / 2;
  const cx = box.x + w;
  const cy = box.y + h;
  const tx = to.x + to.width / 2;
  const ty = to.y + to.height / 2;
  const xx = (tx - cx) / (2 * w) - (ty - cy) / (2 * h);
  const yy = (tx - cx) / (2 * w) + (ty - cy) / (2 * h);
  const a = 1 / (Math.abs(xx) + Math.abs(yy) || 1);
  return { x: w * (a * xx + a * yy) + cx, y: h * (-a * xx + a * yy) + cy };
}

function sideOf(box: Box, point: { x: number; y: number }): Position {
  if (point.x <= box.x + 1) return Position.Left;
  if (point.x >= box.x + box.width - 1) return Position.Right;
  if (point.y <= box.y + 1) return Position.Top;
  return Position.Bottom;
}

/**
 * An arrow that leaves and enters tiles on the sides facing each other,
 * whichever handle it was drawn from, with its comment in the middle.
 */
export function FloatingEdge({
  id,
  source,
  target,
  markerEnd,
  selected,
  data,
}: EdgeProps<CanvasEdge>) {
  const t = useTranslations("CanvasPage");
  const { setLinkLabel, removeLink, live } = useCanvasTiles();
  const pulse = live.pulses.get(id);
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  const [editing, setEditing] = useState(false);
  if (!sourceNode || !targetNode) return null;

  const from = boxOf(sourceNode);
  const to = boxOf(targetNode);
  const start = exitPoint(from, to);
  const end = exitPoint(to, from);
  const [path, labelX, labelY] = getBezierPath({
    sourceX: start.x,
    sourceY: start.y,
    sourcePosition: sideOf(from, start),
    targetX: end.x,
    targetY: end.y,
    targetPosition: sideOf(to, end),
  });
  const label = data?.label ?? "";

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={cn(
          "!stroke-zinc-400 transition-colors dark:!stroke-zinc-500",
          (selected || pulse) && "!stroke-primary"
        )}
        style={{ strokeWidth: selected || pulse ? 2.5 : 1.5 }}
      />
      {pulse && (
        <circle key={pulse} r={6} className="fill-primary">
          <animateMotion dur="1.2s" repeatCount="3" path={path} />
        </circle>
      )}
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan pointer-events-auto absolute flex items-center gap-1"
          style={{
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
          }}
        >
          {editing ? (
            <input
              autoFocus
              defaultValue={label}
              aria-label={t("linkComment")}
              className="h-7 w-48 rounded-md border border-primary/60 bg-background px-2 text-xs outline-none"
              onBlur={(event) => {
                setLinkLabel(id, event.currentTarget.value);
                setEditing(false);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") event.currentTarget.blur();
                if (event.key === "Escape") setEditing(false);
              }}
            />
          ) : label ? (
            <button
              type="button"
              onDoubleClick={() => setEditing(true)}
              title={t("linkEditHint")}
              className={cn(
                "max-w-56 truncate rounded-full border bg-background px-2.5 py-0.5 text-xs shadow-sm",
                selected
                  ? "border-primary/60 text-foreground"
                  : "border-zinc-200 text-muted-foreground dark:border-zinc-700"
              )}
            >
              {label}
            </button>
          ) : selected ? (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-full border border-dashed border-primary/60 bg-background px-2.5 py-0.5 text-xs text-muted-foreground"
            >
              {t("linkAddComment")}
            </button>
          ) : null}
          {selected && !editing && (
            <button
              type="button"
              aria-label={t("linkRemove")}
              onClick={() => removeLink(id)}
              className="flex h-5 w-5 items-center justify-center rounded-full border border-zinc-200 bg-background text-muted-foreground hover:text-foreground dark:border-zinc-700"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

export const EDGE_TYPES = { floating: FloatingEdge };
