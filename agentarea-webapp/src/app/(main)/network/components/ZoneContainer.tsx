"use client";

import { type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";

const colorMap: Record<string, { bg: string; border: string; text: string }> = {
  red:    { bg: "bg-red-50/40 dark:bg-red-950/20",    border: "border-red-200 dark:border-red-800",    text: "text-red-400 dark:text-red-500" },
  amber:  { bg: "bg-amber-50/40 dark:bg-amber-950/20", border: "border-amber-200 dark:border-amber-800", text: "text-amber-500 dark:text-amber-600" },
  blue:   { bg: "bg-blue-50/30 dark:bg-blue-950/20",  border: "border-blue-200 dark:border-blue-800",  text: "text-blue-400 dark:text-blue-500" },
  orange: { bg: "bg-orange-50/40 dark:bg-orange-950/20", border: "border-orange-200 dark:border-orange-800", text: "text-orange-400 dark:text-orange-500" },
  slate:  { bg: "bg-slate-50/40 dark:bg-slate-900/20", border: "border-slate-200 dark:border-slate-700", text: "text-slate-400 dark:text-slate-500" },
};

export default function ZoneContainer({ data }: NodeProps) {
  const d = data as Record<string, any>;
  const colors = colorMap[d.color as string] ?? colorMap.slate;

  return (
    <div
      className={cn(
        "rounded-2xl border border-dashed w-full h-full flex flex-col pointer-events-none",
        colors.bg,
        colors.border
      )}
    >
      <span
        className={cn(
          "text-[10px] font-semibold uppercase tracking-widest px-3 pt-2.5",
          colors.text
        )}
      >
        {d.label as string}
      </span>
    </div>
  );
}
