"use client";

import { Check, X } from "lucide-react";

interface InboxSelectionBarProps {
  checkedCount: number;
  onApprove: () => void;
  onReject: () => void;
  onClear: () => void;
}

export function InboxSelectionBar({
  checkedCount,
  onApprove,
  onReject,
  onClear,
}: InboxSelectionBarProps) {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-primary/10 px-3 py-2">
      <span className="mr-auto text-[12.5px] font-semibold text-primary">
        {checkedCount} selected
      </span>
      <button
        onClick={onApprove}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md bg-emerald-600 px-2.5 text-[12px] font-semibold text-white transition hover:brightness-95"
      >
        <Check size={14} strokeWidth={2.4} /> Approve
      </button>
      <button
        onClick={onReject}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-border bg-background px-2.5 text-[12px] font-semibold text-red-500 transition hover:bg-red-500/5"
      >
        <X size={14} strokeWidth={2.4} /> Reject
      </button>
      <button
        onClick={onClear}
        className="shrink-0 px-1 text-[12px] font-medium text-muted-foreground hover:text-foreground"
      >
        Clear
      </button>
    </div>
  );
}
