"use client";

import { Handle, Position } from "@xyflow/react";
import { AlertTriangle, ExternalLink } from "lucide-react";
import Link from "next/link";
import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface NodeCardProps {
  icon: ReactNode;
  label: string;
  subtitle: string;
  badge?: ReactNode;
  href?: string;
  riskLevel?: "none" | "warning" | "critical";
  color?: "blue" | "green" | "purple" | "amber" | "rose" | "neutral";
  hasTarget?: boolean;
  hasSource?: boolean;
  dimmed?: boolean;
  highlighted?: boolean;
}

const colorMap = {
  blue: {
    border: "border-blue-300/80 dark:border-blue-700/80",
    bg: "bg-blue-50 dark:bg-blue-950/40",
    icon: "text-blue-500 dark:text-blue-400",
    ring: "group-hover:ring-blue-200 dark:group-hover:ring-blue-900/40",
  },
  green: {
    border: "border-emerald-300/80 dark:border-emerald-700/80",
    bg: "bg-emerald-50 dark:bg-emerald-950/40",
    icon: "text-emerald-500 dark:text-emerald-400",
    ring: "group-hover:ring-emerald-200 dark:group-hover:ring-emerald-900/40",
  },
  purple: {
    border: "border-purple-300/80 dark:border-purple-700/80",
    bg: "bg-purple-50 dark:bg-purple-950/40",
    icon: "text-purple-500 dark:text-purple-400",
    ring: "group-hover:ring-purple-200 dark:group-hover:ring-purple-900/40",
  },
  amber: {
    border: "border-amber-300/80 dark:border-amber-700/80",
    bg: "bg-amber-50 dark:bg-amber-950/40",
    icon: "text-amber-500 dark:text-amber-400",
    ring: "group-hover:ring-amber-200 dark:group-hover:ring-amber-900/40",
  },
  rose: {
    border: "border-rose-300/80 dark:border-rose-700/80",
    bg: "bg-rose-50 dark:bg-rose-950/40",
    icon: "text-rose-500 dark:text-rose-400",
    ring: "group-hover:ring-rose-200 dark:group-hover:ring-rose-900/40",
  },
  neutral: {
    border: "border-zinc-200 dark:border-zinc-700",
    bg: "bg-white dark:bg-zinc-900",
    icon: "text-zinc-500 dark:text-zinc-400",
    ring: "group-hover:ring-zinc-200 dark:group-hover:ring-zinc-800",
  },
};

export default function NodeCard({
  icon,
  label,
  subtitle,
  badge,
  href,
  riskLevel = "none",
  color = "blue",
  hasTarget = true,
  hasSource = true,
  dimmed = false,
  highlighted = false,
}: NodeCardProps) {
  const c = colorMap[color];
  return (
    <div
      className={cn(
        "group flex w-[128px] flex-col items-center transition-opacity duration-200",
        dimmed && !highlighted && "opacity-25"
      )}
    >
      <div
        className={cn(
          "relative flex h-14 w-14 items-center justify-center rounded-xl border-2 shadow-sm ring-4 ring-transparent transition-all",
          "group-hover:-translate-y-0.5 group-hover:shadow-md",
          c.border,
          c.bg,
          c.ring,
          riskLevel === "critical" && "border-red-400 dark:border-red-700",
          riskLevel === "warning" &&
            "ring-orange-100 dark:ring-orange-900/30",
          highlighted &&
            "border-blue-500 ring-blue-200 dark:border-blue-400 dark:ring-blue-900/60"
        )}
      >
        {hasTarget && (
          <Handle
            type="target"
            position={Position.Left}
            isConnectable={false}
            className="!pointer-events-none !h-1 !w-1 !border-0 !bg-transparent !opacity-0"
          />
        )}
        <Handle
          id="top"
          type="target"
          position={Position.Top}
          isConnectable={false}
            className="!pointer-events-none !h-1 !w-1 !border-0 !bg-transparent !opacity-0"
        />

        <span className={cn("flex items-center justify-center", c.icon)}>
          {icon}
        </span>

        {riskLevel !== "none" && (
          <AlertTriangle
            className={cn(
              "absolute -right-1.5 -top-1.5 h-3.5 w-3.5",
              riskLevel === "critical" ? "text-red-500" : "text-orange-500"
            )}
          />
        )}

        {hasSource && (
          <Handle
            type="source"
            position={Position.Right}
            isConnectable={false}
            className="!pointer-events-none !h-1 !w-1 !border-0 !bg-transparent !opacity-0"
          />
        )}
        <Handle
          id="bottom"
          type="source"
          position={Position.Bottom}
          isConnectable={false}
            className="!pointer-events-none !h-1 !w-1 !border-0 !bg-transparent !opacity-0"
        />
      </div>

      <div className="mt-2 flex w-full min-w-0 flex-col items-center text-center">
        <p className="w-full truncate text-[12px] font-semibold leading-tight text-foreground">
          {label}
        </p>
        <p className="mt-0.5 w-full truncate text-[10px] leading-tight text-muted-foreground">
          {subtitle}
        </p>
        {badge && <div className="mt-1 flex items-center justify-center">{badge}</div>}
        {href && (
          <Link
            href={href}
            onClick={(e) => e.stopPropagation()}
            className="mt-1 inline-flex"
          >
            <ExternalLink className="h-3 w-3 text-muted-foreground transition-colors hover:text-foreground" />
          </Link>
        )}
      </div>
    </div>
  );
}
