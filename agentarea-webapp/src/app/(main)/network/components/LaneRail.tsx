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
    bg: "bg-blue-50/25 dark:bg-blue-950/10",
    border: "border-blue-300/60 dark:border-blue-800/50",
    chip: "bg-white/90 dark:bg-blue-950/50 ring-1 ring-blue-200/80 dark:ring-blue-800/70",
    icon: "text-blue-600 dark:text-blue-300",
    label: "text-blue-700 dark:text-blue-300",
    glow: "from-blue-500/10",
  },
  neutral: {
    bg: "bg-white/35 dark:bg-zinc-900/20",
    border: "border-zinc-300/70 dark:border-zinc-700/60",
    chip: "bg-white/95 dark:bg-zinc-900/70 ring-1 ring-zinc-200/90 dark:ring-zinc-700/80",
    icon: "text-zinc-700 dark:text-zinc-200",
    label: "text-zinc-800 dark:text-zinc-100",
    glow: "from-slate-500/10",
  },
  rose: {
    bg: "bg-violet-50/20 dark:bg-violet-950/10",
    border: "border-violet-300/60 dark:border-violet-800/50",
    chip: "bg-white/90 dark:bg-violet-950/50 ring-1 ring-violet-200/80 dark:ring-violet-800/70",
    icon: "text-blue-600 dark:text-blue-300",
    label: "text-zinc-800 dark:text-zinc-100",
    glow: "from-violet-500/10",
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
        "pointer-events-none relative h-full w-full overflow-hidden rounded-lg border border-dashed shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]",
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
      <div className="absolute inset-0 opacity-45 [background-image:linear-gradient(rgba(37,99,235,0.10)_1px,transparent_1px),linear-gradient(90deg,rgba(37,99,235,0.10)_1px,transparent_1px)] [background-size:24px_24px]" />
      <div className="flex items-center gap-2.5 px-5 pt-4">
        <span
          className={cn(
            "relative flex h-7 w-7 items-center justify-center rounded-md shadow-sm",
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
