"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import ToolbarSelect from "@/components/ToolbarSelect";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";
import type { DispositionFilter as Filter } from "@/lib/streamOutcome";

const OPTIONS: Filter[] = ["all", "reacted", "skipped", "error", "unheard"];

/**
 * Narrows the feed to events with one outcome. A select rather than a
 * CountSegmentedControl: per-outcome counts for a whole stream are not
 * something the feed page loads.
 */
export default function DispositionFilter({ current }: { current: Filter }) {
  const t = useTranslations("EventsPage.filter");
  const tFeed = useTranslations("EventsPage.feed");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const select = (value: Filter) => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("before");
    params.delete("event");
    if (value === "all") params.delete("outcome");
    else params.set("outcome", value);
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <ToolbarSelect<Filter>
      label={tFeed("outcome")}
      groups={[OPTIONS.map((value) => ({ value, label: t(value) }))]}
      value={current}
      onChange={select}
    />
  );
}
