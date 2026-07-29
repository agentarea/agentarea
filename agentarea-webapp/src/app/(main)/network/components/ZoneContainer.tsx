"use client";

import { type Node, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";

interface ZoneData extends Record<string, unknown> {
  label: string;
}

export default function ZoneContainer({ data }: NodeProps<Node<ZoneData>>) {
  return (
    <div
      className={cn(
        "pointer-events-none flex h-full w-full flex-col rounded-2xl border border-dashed",
        "border-zinc-200 bg-zinc-50/40 dark:border-zinc-800 dark:bg-zinc-900/30"
      )}
    >
      <span className="px-3 pt-2.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
        {data.label}
      </span>
    </div>
  );
}
