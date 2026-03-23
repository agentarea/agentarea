"use client";

import { Handle, Position } from "@xyflow/react";
import { ExternalLink, AlertTriangle } from "lucide-react";
import { type ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface NodeCardProps {
  icon: ReactNode;
  category: string;
  label: string;
  metadata?: ReactNode;
  href?: string;
  riskLevel?: "none" | "warning" | "critical";
  color?: "blue" | "green" | "purple" | "amber";
  hasTarget?: boolean;
  hasSource?: boolean;
}

const colorMap = {
  blue: "text-blue-500",
  green: "text-green-500",
  purple: "text-purple-500",
  amber: "text-amber-500",
};

const riskColors = {
  none: "",
  warning: "border-orange-300 dark:border-orange-700",
  critical: "border-red-400 dark:border-red-700",
};

export default function NodeCard({
  icon,
  category,
  label,
  metadata,
  href,
  riskLevel = "none",
  color = "blue",
  hasTarget = true,
  hasSource = true,
}: NodeCardProps) {
  return (
    <div
      className={cn(
        "bg-white dark:bg-zinc-800 rounded-xl shadow-sm border border-zinc-200 dark:border-zinc-700 min-w-[200px] max-w-[240px] px-3.5 py-3",
        riskLevel !== "none" && riskColors[riskLevel]
      )}
    >
      {hasTarget && (
        <Handle type="target" position={Position.Left} className="!bg-zinc-300 dark:!bg-zinc-600 !w-2 !h-2 !border-0" />
      )}

      <div className="flex items-center justify-between gap-2 mb-1.5">
        <div className={cn("flex items-center gap-1.5 text-xs text-muted-foreground", colorMap[color])}>
          <span className="shrink-0">{icon}</span>
          <span className="font-medium">{category}</span>
        </div>
        <div className="flex items-center gap-1">
          {riskLevel !== "none" && (
            <AlertTriangle
              className={cn("h-3 w-3 shrink-0", riskLevel === "critical" ? "text-red-500" : "text-orange-500")}
            />
          )}
          {href && (
            <Link href={href} onClick={(e) => e.stopPropagation()}>
              <ExternalLink className="h-3 w-3 text-muted-foreground hover:text-foreground transition-colors shrink-0" />
            </Link>
          )}
        </div>
      </div>

      <p className="text-sm font-semibold text-foreground leading-tight truncate">{label}</p>

      {metadata && <div className="mt-1.5">{metadata}</div>}

      {hasSource && (
        <Handle type="source" position={Position.Right} className="!bg-zinc-300 dark:!bg-zinc-600 !w-2 !h-2 !border-0" />
      )}
    </div>
  );
}
