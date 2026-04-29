"use client";

import { type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";

export default function ZoneContainer({ data }: NodeProps) {
  const d = data as Record<string, any>;
  return (
    <div
      className={cn(
        "pointer-events-none flex h-full w-full flex-col rounded-2xl border border-dashed",
        "border-zinc-200 bg-zinc-50/40 dark:border-zinc-800 dark:bg-zinc-900/30"
      )}
    >
      <span className="px-3 pt-2.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
        {d.label as string}
      </span>
    </div>
  );
}
