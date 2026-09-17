"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

export function InboxToolbar({ counts, filter, onChange }: InboxToolbarProps) {
  return (
    <div className="flex h-full min-w-0 w-full items-center gap-3">
      <Select value={filter} onValueChange={(value) => onChange(value as FilterValue)}>
        <SelectTrigger
          aria-label="Filter inbox tasks"
          className="h-8 w-auto min-w-[158px] border-border bg-transparent px-2.5 text-[12.5px] shadow-none"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start">
          {FILTERS.map((item) => (
            <SelectItem key={item.key} value={item.key}>
              <span className="flex items-center gap-2">
                {item.label}
                <span className="text-muted-foreground">{counts[item.key]}</span>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
