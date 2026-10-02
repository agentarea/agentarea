"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Clock, MessagesSquare, Webhook } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";

export interface TriggerTypeCounts {
  all: number;
  channel: number;
  event: number;
  schedule: number;
}

interface TriggersTypeFilterProps {
  currentType: string;
  counts: TriggerTypeCounts;
}

const LANE_ICON: Record<string, LucideIcon | undefined> = {
  channel: MessagesSquare,
  event: Webhook,
  schedule: Clock,
};

/**
 * Segmented filter over what starts an automation. Drives the `type` URL param;
 * "all" clears it.
 *
 * The lanes are channel / event / schedule rather than cron / webhook: the
 * latter names the transport, which tells nobody whether a row is a Telegram
 * bot they have to stand up or a GitHub hook that just arrives.
 */
export default function TriggersTypeFilter({
  currentType,
  counts,
}: TriggersTypeFilterProps) {
  const t = useTranslations("TriggersPage.filter");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const active = currentType || "all";

  const tabs = [
    { value: "all", label: t("all"), count: counts.all },
    { value: "channel", label: t("channels"), count: counts.channel },
    { value: "event", label: t("events"), count: counts.event },
    { value: "schedule", label: t("schedules"), count: counts.schedule },
  ];

  const select = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "all") {
      params.delete("type");
    } else {
      params.set("type", value);
    }
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  // The subtle (grey) pill, same as the inbox status filter: this narrows the
  // list rather than navigating the page.
  return (
    <CountSegmentedControl
      items={tabs.map((tab) => {
        const Icon = LANE_ICON[tab.value];
        return {
          value: tab.value,
          label: (
            <span className="flex items-center gap-1.5 whitespace-nowrap">
              {Icon && <Icon className="h-4 w-4" strokeWidth={1.8} />}
              {tab.label}
            </span>
          ),
          count: tab.count,
        };
      })}
      value={active}
      onChange={select}
      layoutId="triggers-type-filter"
    />
  );
}
