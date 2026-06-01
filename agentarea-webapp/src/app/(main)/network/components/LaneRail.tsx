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
  }
> = {
  blue: {
    bg: "bg-blue-50/60 dark:bg-blue-950/20",
    border: "border-blue-200/70 dark:border-blue-900/50",
    chip: "bg-white/80 dark:bg-blue-950/40 ring-1 ring-blue-200/60 dark:ring-blue-900/60",
    icon: "text-blue-500 dark:text-blue-400",
    label: "text-blue-700 dark:text-blue-300",
  },
  neutral: {
    bg: "bg-zinc-50/70 dark:bg-zinc-900/40",
    border: "border-zinc-200/80 dark:border-zinc-800/70",
    chip: "bg-white/90 dark:bg-zinc-900/60 ring-1 ring-zinc-200/80 dark:ring-zinc-800/80",
    icon: "text-zinc-600 dark:text-zinc-300",
    label: "text-zinc-700 dark:text-zinc-200",
  },
  rose: {
    bg: "bg-rose-50/60 dark:bg-rose-950/20",
    border: "border-rose-200/70 dark:border-rose-900/50",
    chip: "bg-white/80 dark:bg-rose-950/40 ring-1 ring-rose-200/60 dark:ring-rose-900/60",
    icon: "text-rose-500 dark:text-rose-400",
    label: "text-rose-700 dark:text-rose-300",
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
        "pointer-events-none relative h-full w-full overflow-hidden rounded-3xl border",
        tone.bg,
        tone.border
      )}
    >
      <div className="flex items-center gap-2.5 px-5 pt-4">
        <span
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-lg shadow-sm",
            tone.chip
          )}
        >
          <Icon className={cn("h-3.5 w-3.5", tone.icon)} />
        </span>
        <span
          className={cn(
            "text-[11px] font-semibold uppercase tracking-[0.16em]",
            tone.label
          )}
        >
          {d.label}
        </span>
      </div>
      {d.sublabel && (
        <p className="px-5 pt-1 text-[10px] leading-tight text-muted-foreground">
          {d.sublabel}
        </p>
      )}
    </div>
  );
}
