"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Clock, MessagesSquare, Webhook } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

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
  const router = useRouter();
  const pathname = usePathname();
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

  return (
    <div className="flex shrink-0 items-center gap-0.5" role="group">
      {tabs.map((tab) => {
        const isActive = active === tab.value;
        const Icon = LANE_ICON[tab.value];
        return (
          <button
            key={tab.value}
            type="button"
            aria-pressed={isActive}
            onClick={() => select(tab.value)}
            className={cn(
              "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
              isActive
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            )}
          >
            {Icon && <Icon aria-hidden="true" className="h-3.5 w-3.5" />}
            <span>{tab.label}</span>
            <span
              className={cn(
                "tabular-nums text-xs",
                isActive ? "text-muted-foreground" : "text-muted-foreground/60"
              )}
            >
              {tab.count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
