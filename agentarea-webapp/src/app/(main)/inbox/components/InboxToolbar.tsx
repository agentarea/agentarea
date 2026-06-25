"use client";

import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  FILTERS,
  STATUS_LABEL,
  type InboxCounts,
  type FilterValue,
} from "@/app/(main)/inbox/components/inboxShared";

interface InboxToolbarProps {
  counts: InboxCounts;
  filter: FilterValue;
  visibleCount: number;
  onChange: (next: FilterValue) => void;
}

export function InboxToolbar({
  counts,
  filter,
  visibleCount,
  onChange,
}: InboxToolbarProps) {
  return (
    <div className="flex h-[46px] w-full items-center gap-3">
      <CountSegmentedControl
        items={FILTERS.map((item) => ({
          value: item.key,
          label: item.label,
          count: counts[item.key],
        }))}
        value={filter}
        onChange={onChange}
        layoutId="inbox-filter-control"
      />
      <div className="flex-1" />
      {filter !== "pending" || counts.pending > 0 ? (
        <div className="text-[12.5px] text-muted-foreground">
          {filter === "pending" ? (
            <>
              <b className="font-semibold text-foreground">{counts.pending}</b>{" "}
              awaiting approval
            </>
          ) : (
            <>
              <b className="font-semibold text-foreground">{visibleCount}</b>{" "}
              {filter === "all" ? "tasks" : STATUS_LABEL[filter].toLowerCase()}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
