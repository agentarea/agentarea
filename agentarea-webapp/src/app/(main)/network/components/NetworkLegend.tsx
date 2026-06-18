"use client";

import { useState } from "react";
import {
  Bot,
  ChevronDown,
  ChevronUp,
  Clock,
  Globe,
  Info,
  Plug,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

const items: Array<{
  Icon: typeof Bot;
  label: string;
  desc: string;
  dot: string;
}> = [
  {
    Icon: Globe,
    label: "Webhook trigger",
    desc: "External event entering the network",
    dot: "bg-amber-400",
  },
  {
    Icon: Clock,
    label: "Schedule trigger",
    desc: "Cron / timer driven",
    dot: "bg-zinc-300",
  },
  {
    Icon: Bot,
    label: "Agent",
    desc: "Internal — governed by VPC policy",
    dot: "bg-zinc-300",
  },
  {
    Icon: Plug,
    label: "MCP server",
    desc: "Green = egress (calls external); grey = private",
    dot: "bg-emerald-400",
  },
  {
    Icon: Globe,
    label: "OpenAPI connection",
    desc: "External REST API (always egress)",
    dot: "bg-rose-400",
  },
  {
    Icon: Sparkles,
    label: "Skill",
    desc: "Shown standalone only when egress",
    dot: "bg-sky-400",
  },
];

export default function NetworkLegend() {
  const [open, setOpen] = useState(false);

  return (
    <div className="absolute right-4 top-4 z-10">
      <div
        className={cn(
          "rounded-lg border border-blue-100/80 bg-white/90 shadow-[0_18px_60px_rgba(15,23,42,0.08)] backdrop-blur-xl",
          "dark:border-blue-900/50 dark:bg-zinc-950/85"
        )}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold text-zinc-800 hover:text-zinc-950 dark:text-zinc-200 dark:hover:text-zinc-50"
        >
          <Info className="h-3.5 w-3.5 text-blue-500" />
          <span className="uppercase tracking-[0.14em]">Boundary key</span>
          {open ? (
            <ChevronUp className="ml-auto h-3.5 w-3.5 text-zinc-400" />
          ) : (
            <ChevronDown className="ml-auto h-3.5 w-3.5 text-zinc-400" />
          )}
        </button>
        {open && (
          <div className="space-y-2 border-t border-blue-50 px-3 py-2.5 dark:border-blue-900/40">
            {items.map(({ Icon, label, desc, dot }) => (
              <div key={label} className="flex items-start gap-2">
                <span
                  className={cn(
                    "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full shadow-[0_0_0_3px_rgba(255,255,255,0.9)]",
                    dot
                  )}
                />
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-500" />
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold text-zinc-900 dark:text-zinc-100">
                    {label}
                  </p>
                  <p className="text-[10px] leading-tight text-muted-foreground">
                    {desc}
                  </p>
                </div>
              </div>
            ))}
            <div className="mt-2 border-t border-blue-50 pt-2 dark:border-blue-900/40">
              <p className="text-[10px] leading-tight text-muted-foreground">
                <span className="font-semibold text-zinc-800 dark:text-zinc-200">
                  Click a node
                </span>{" "}
                — its full reachable subgraph stays bright; everything else
                fades.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
