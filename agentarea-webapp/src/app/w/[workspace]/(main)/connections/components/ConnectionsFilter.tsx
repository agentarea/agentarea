"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { CircleAlert, ShieldOff, Unplug } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { LIST_FILTERS, type ListFilter } from "../list-sections";

const FILTER_ICON: Record<ListFilter, LucideIcon | undefined> = {
  all: undefined,
  attention: CircleAlert,
  unused: Unplug,
  unrestricted: ShieldOff,
};

/**
 * Segmented filter over the connections list. Drives the `filter` URL param;
 * "all" clears it.
 */
export default function ConnectionsFilter({
  currentFilter,
  counts,
}: {
  currentFilter: ListFilter;
  counts: Record<ListFilter, number>;
}) {
  const t = useTranslations("MCPServersPage.listFilters");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const select = (value: ListFilter) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "all") {
      params.delete("filter");
    } else {
      params.set("filter", value);
    }
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  // The subtle (grey) pill, same as the automation and inbox filters: this
  // narrows the list rather than navigating the page.
  return (
    <CountSegmentedControl<ListFilter>
      items={LIST_FILTERS.map((key) => {
        const Icon = FILTER_ICON[key];
        return {
          value: key,
          label: (
            <span className="flex items-center gap-1.5 whitespace-nowrap">
              {Icon && <Icon className="h-4 w-4" strokeWidth={1.8} />}
              {t(key)}
            </span>
          ),
          count: counts[key],
        };
      })}
      value={currentFilter}
      onChange={select}
      layoutId="connections-filter"
    />
  );
}
