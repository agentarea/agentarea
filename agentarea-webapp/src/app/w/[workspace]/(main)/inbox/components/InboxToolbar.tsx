"use client";

import { useTranslations } from "next-intl";
import {
  CircleAlert,
  CircleCheck,
  CircleX,
  History,
  Inbox,
  MessageCircleQuestion,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  FILTER_KEYS,
  type FilterValue,
  type InboxCounts,
} from "@/app/w/[workspace]/(main)/inbox/components/inboxShared";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";

interface InboxToolbarProps {
  counts: InboxCounts;
  filter: FilterValue;
  onChange: (next: FilterValue) => void;
}

const FILTER_ICON: Record<FilterValue, LucideIcon> = {
  all: Inbox,
  pending: CircleAlert,
  input: MessageCircleQuestion,
  completed: CircleCheck,
  failed: CircleX,
  decided: History,
};

// The subtle (grey) pill: this filters the task list rather than navigating
// the page, so it stays quieter than the selected row beneath it.
export function InboxToolbar({ counts, filter, onChange }: InboxToolbarProps) {
  const t = useTranslations("InboxPage.filters");

  return (
    <SubheaderToolbar
      categories={
        <CountSegmentedControl<FilterValue>
          items={FILTER_KEYS.map((key) => {
            const Icon = FILTER_ICON[key];
            return {
              value: key,
              label: (
                <span className="flex items-center gap-1.5 whitespace-nowrap">
                  <Icon className="h-4 w-4" strokeWidth={1.8} />
                  {t(key)}
                </span>
              ),
              count: counts[key],
            };
          })}
          value={filter}
          onChange={onChange}
          layoutId="inbox-filter-control"
        />
      }
    />
  );
}
