"use client";

import { type NodeProps } from "@xyflow/react";
import { Bot, Network, Zap, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type LaneTone = "blue" | "neutral" | "rose";

const TONE: Record<
  LaneTone,
  {
    bg: string;
    border: string;
    chip: string;
    icon: string;
    label: string;
    glow: string;
  }
> = {
  blue: {
    bg: "bg-amber-50/35 dark:bg-amber-950/10",
    border: "border-amber-300/70 dark:border-amber-800/50",
    chip: "bg-white/90 dark:bg-amber-950/50 ring-1 ring-amber-200/80 dark:ring-amber-800/70",
    icon: "text-amber-600 dark:text-amber-300",
    label: "text-amber-700 dark:text-amber-300",
    glow: "from-amber-400/10",
  },
  neutral: {
    bg: "bg-indigo-50/35 dark:bg-indigo-950/10",
    border: "border-indigo-300/70 dark:border-indigo-800/50",
    chip: "bg-white/95 dark:bg-indigo-950/50 ring-1 ring-indigo-200/90 dark:ring-indigo-800/70",
    icon: "text-indigo-600 dark:text-indigo-300",
    label: "text-indigo-700 dark:text-indigo-300",
    glow: "from-indigo-500/10",
  },
  rose: {
    bg: "bg-emerald-50/30 dark:bg-emerald-950/10",
    border: "border-emerald-300/70 dark:border-emerald-800/50",
    chip: "bg-white/90 dark:bg-emerald-950/50 ring-1 ring-emerald-200/80 dark:ring-emerald-800/70",
    icon: "text-emerald-600 dark:text-emerald-300",
    label: "text-emerald-700 dark:text-emerald-300",
    glow: "from-emerald-400/10",
  },
};

const ICON_MAP: Record<string, LucideIcon> = {
  events: Zap,
  agents: Bot,
  external: Network,
};

export default function LaneRail({ data }: NodeProps) {
  const d = data as {
    label: string;
    sublabel?: string;
    tone?: LaneTone;
    iconKey?: string;
  };
  const tone = TONE[d.tone ?? "neutral"];
  const Icon = ICON_MAP[d.iconKey ?? ""] ?? Network;

  return (
    <div
      className={cn(
        "pointer-events-none relative h-full w-full overflow-hidden rounded-xl border border-dashed shadow-[inset_0_1px_0_rgba(255,255,255,0.85)]",
        tone.bg,
        tone.border
      )}
    >
      <div
        className={cn(
          "absolute inset-x-0 top-0 h-24 bg-gradient-to-b to-transparent",
          tone.glow
        )}
      />
      <div className="flex items-center gap-2.5 px-4 pt-3.5">
        <span
          className={cn(
            "relative flex h-6 w-6 items-center justify-center rounded-md shadow-sm",
            tone.chip
          )}
        >
          <Icon className={cn("h-3 w-3", tone.icon)} />
        </span>
        <span
          className={cn(
            "font-mono text-[10px] font-semibold uppercase tracking-[0.16em]",
            tone.label
          )}
        >
          {d.label}
        </span>
      </div>
      {d.sublabel && (
        <p className="px-4 pt-1 text-[9px] leading-tight text-muted-foreground">
          {d.sublabel}
        </p>
      )}
    </div>
  );
}
