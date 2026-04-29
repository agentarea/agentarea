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
    dot: "bg-purple-400",
  },
];

export default function NetworkLegend() {
  const [open, setOpen] = useState(false);

  return (
    <div className="absolute right-4 top-4 z-10">
      <div
        className={cn(
          "rounded-xl border border-zinc-200 bg-white/95 shadow-sm backdrop-blur",
          "dark:border-zinc-800 dark:bg-zinc-900/90"
        )}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-100"
        >
          <Info className="h-3.5 w-3.5 text-zinc-400" />
          <span>Legend</span>
          {open ? (
            <ChevronUp className="ml-auto h-3.5 w-3.5 text-zinc-400" />
          ) : (
            <ChevronDown className="ml-auto h-3.5 w-3.5 text-zinc-400" />
          )}
        </button>
        {open && (
          <div className="space-y-1.5 border-t border-zinc-100 px-3 py-2 dark:border-zinc-800">
            {items.map(({ Icon, label, desc, dot }) => (
              <div key={label} className="flex items-start gap-2">
                <span
                  className={cn(
                    "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                    dot
                  )}
                />
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-500" />
                <div className="min-w-0">
                  <p className="text-[11px] font-medium text-zinc-800 dark:text-zinc-200">
                    {label}
                  </p>
                  <p className="text-[10px] leading-tight text-muted-foreground">
                    {desc}
                  </p>
                </div>
              </div>
            ))}
            <div className="mt-2 border-t border-zinc-100 pt-2 dark:border-zinc-800">
              <p className="text-[10px] leading-tight text-muted-foreground">
                <span className="font-medium text-zinc-700 dark:text-zinc-300">
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
