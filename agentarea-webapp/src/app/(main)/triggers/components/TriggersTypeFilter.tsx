"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";

export interface TriggerTypeCounts {
  all: number;
  cron: number;
  webhook: number;
}

interface TriggersTypeFilterProps {
  currentType: string;
  counts: TriggerTypeCounts;
}

/**
 * Linear-style segmented filter — All / Cron / Webhook with live counts.
 * Drives the `type` URL param; "all" clears it.
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
    { value: "cron", label: t("cron"), count: counts.cron },
    { value: "webhook", label: t("webhook"), count: counts.webhook },
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
