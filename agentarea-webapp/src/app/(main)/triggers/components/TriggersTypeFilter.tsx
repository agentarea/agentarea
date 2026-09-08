"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";

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
 * All / Cron / Webhook filter with live counts — reuses the shared
 * `CountSegmentedControl` (same animated pill as the Inbox toolbar).
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

  const items = [
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
    <CountSegmentedControl
      items={items}
      value={active}
      onChange={select}
      layoutId="triggers-type-filter"
      className="w-full sm:w-auto"
      itemClassName="px-2 sm:px-3"
    />
  );
}
