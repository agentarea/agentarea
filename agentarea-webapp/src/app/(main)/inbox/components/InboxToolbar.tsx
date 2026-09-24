"use client";

import { CircleAlert, CircleCheck, CircleX, Inbox } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  FILTERS,
  type InboxCounts,
  type FilterValue,
} from "@/app/(main)/inbox/components/inboxShared";

interface InboxToolbarProps {
  counts: InboxCounts;
  filter: FilterValue;
  onChange: (next: FilterValue) => void;
}

const FILTER_ICON: Record<FilterValue, LucideIcon> = {
  all: Inbox,
  pending: CircleAlert,
  completed: CircleCheck,
  failed: CircleX,
};

// The subtle (grey) pill: this filters the task list rather than navigating
// the page, so it stays quieter than the selected row beneath it.
export function InboxToolbar({ counts, filter, onChange }: InboxToolbarProps) {
  return (
    <div className="flex h-full min-w-0 w-full items-center">
      <CountSegmentedControl<FilterValue>
        items={FILTERS.map((item) => {
          const Icon = FILTER_ICON[item.key];
          return {
            value: item.key,
            label: (
              <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Icon className="h-4 w-4" strokeWidth={1.8} />
                {item.label}
              </span>
            ),
            count: counts[item.key],
          };
        })}
        value={filter}
        onChange={onChange}
        layoutId="inbox-filter-control"
      />
    </div>
  );
}
