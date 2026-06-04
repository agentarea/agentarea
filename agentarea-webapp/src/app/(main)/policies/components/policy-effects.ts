import type { PolicyEffect } from "@/types/policies";

// Shared effect color tokens used by both the read-only PolicyRulesView and the
// editable PolicyEditor so the two stay visually consistent.
export const EFFECT_STYLES: Record<
  PolicyEffect,
  { label: string; dot: string; chip: string }
> = {
  allow: {
    label: "Allow",
    dot: "bg-emerald-500",
    chip: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  },
  cap: {
    label: "Cap",
    dot: "bg-blue-500",
    chip: "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  },
  approval: {
    label: "Approval",
    dot: "bg-amber-500",
    chip: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  },
  deny: {
    label: "Deny",
    dot: "bg-red-500",
    chip: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
  },
  safety: {
    label: "Safety",
    dot: "bg-violet-500",
    chip: "bg-violet-50 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
  },
};
