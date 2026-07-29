"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { Handle, Position } from "@xyflow/react";
import { AlertTriangle, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

interface NodeCardProps {
  icon: ReactNode;
  label: string;
  subtitle: string;
  badge?: ReactNode;
  href?: string;
  riskLevel?: "none" | "warning" | "critical";
  color?: "blue" | "green" | "sky" | "amber" | "rose" | "neutral";
  hasTarget?: boolean;
  hasSource?: boolean;
  dimmed?: boolean;
  highlighted?: boolean;
}

const colorMap = {
  blue: {
    border: "border-blue-200 dark:border-blue-800/80",
    bg: "bg-blue-50/80 dark:bg-blue-950/40",
    icon: "text-blue-600 dark:text-blue-300",
    ring: "group-hover:ring-blue-100 dark:group-hover:ring-blue-900/40",
    accent: "bg-blue-500",
  },
  green: {
    border: "border-emerald-200 dark:border-emerald-800/80",
    bg: "bg-emerald-50/80 dark:bg-emerald-950/40",
    icon: "text-emerald-600 dark:text-emerald-300",
    ring: "group-hover:ring-emerald-100 dark:group-hover:ring-emerald-900/40",
    accent: "bg-emerald-500",
  },
  sky: {
    border: "border-sky-200 dark:border-sky-800/80",
    bg: "bg-sky-50/80 dark:bg-sky-950/40",
    icon: "text-sky-600 dark:text-sky-300",
    ring: "group-hover:ring-sky-100 dark:group-hover:ring-sky-900/40",
    accent: "bg-sky-500",
  },
  amber: {
    border: "border-amber-200 dark:border-amber-800/80",
    bg: "bg-amber-50/80 dark:bg-amber-950/40",
    icon: "text-amber-600 dark:text-amber-300",
    ring: "group-hover:ring-amber-100 dark:group-hover:ring-amber-900/40",
    accent: "bg-amber-500",
  },
  rose: {
    border: "border-blue-200 dark:border-blue-800/80",
    bg: "bg-white dark:bg-zinc-950",
    icon: "text-blue-600 dark:text-blue-300",
    ring: "group-hover:ring-blue-100 dark:group-hover:ring-blue-900/40",
    accent: "bg-violet-400",
  },
  neutral: {
    border: "border-zinc-200 dark:border-zinc-700/80",
    bg: "bg-white/95 dark:bg-zinc-950",
    icon: "text-zinc-700 dark:text-zinc-200",
    ring: "group-hover:ring-zinc-200 dark:group-hover:ring-zinc-800",
    accent: "bg-blue-500",
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
        "group flex w-[192px] flex-col items-center transition-opacity duration-200",
        dimmed && !highlighted && "opacity-25"
      )}
    >
      <div
        className={cn(
          "relative w-full overflow-hidden rounded-xl border bg-white/95 px-3 py-2.5 shadow-[0_6px_18px_rgba(51,65,85,0.09)] ring-2 ring-transparent backdrop-blur transition-all",
          "group-hover:-translate-y-0.5 group-hover:shadow-[0_10px_26px_rgba(51,65,85,0.14)]",
          c.border,
          c.bg,
          c.ring,
          riskLevel === "critical" && "border-red-400 dark:border-red-700",
          riskLevel === "warning" && "ring-orange-100 dark:ring-orange-900/30",
          highlighted &&
            "border-[#4f67e8] ring-indigo-200 dark:border-indigo-400 dark:ring-indigo-900/60"
        )}
      >
        <span className={cn("absolute inset-y-0 left-0 w-1", c.accent)} />
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

        <div className="relative flex items-center gap-2.5">
          <span
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/80 bg-white/90 shadow-sm dark:border-zinc-700/70 dark:bg-zinc-900/80",
              c.icon
            )}
          >
            {icon}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[12px] font-semibold leading-tight text-zinc-950 dark:text-zinc-50">
              {label}
            </p>
            <p className="mt-1 truncate font-mono text-[9px] font-medium uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">
              {subtitle}
            </p>
            {(badge || href) && (
              <div className="mt-1.5 flex min-h-4 items-center gap-1.5">
                {badge}
                {href && (
                  <Link
                    href={href}
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex"
                  >
                    <ExternalLink className="h-3 w-3 text-muted-foreground transition-colors hover:text-foreground" />
                  </Link>
                )}
              </div>
            )}
          </div>
        </div>

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
    </div>
  );
}
