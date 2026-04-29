"use client";

import { type NodeProps } from "@xyflow/react";

export default function LaneRail({ data }: NodeProps) {
  const d = data as Record<string, any>;
  return (
    <div className="pointer-events-none flex h-full w-full flex-col rounded-2xl border border-dashed border-zinc-200 bg-zinc-50/40 dark:border-zinc-800 dark:bg-zinc-900/30">
      <div className="px-4 pt-3">
        <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-400 dark:text-zinc-500">
          {d.label}
        </span>
        {d.sublabel && (
          <p className="mt-0.5 text-[10px] text-zinc-400 dark:text-zinc-600">
            {d.sublabel}
          </p>
        )}
      </div>
    </div>
  );
}
