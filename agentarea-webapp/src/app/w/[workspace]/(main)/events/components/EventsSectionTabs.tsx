"use client";

import { useTranslations } from "next-intl";
import { Activity } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";
import { EntityIcon } from "@/lib/entity-icons";

const TABS = [
  { href: "/events", labelKey: "events" },
  { href: "/events/streams", labelKey: "streams" },
] as const;

/**
 * The feed and the streams it is read from are two pages of one section,
 * switched here like Models' connected/available: solid, because it swaps the
 * page's content rather than filtering it. The query stays behind, the two
 * pages filter by different things.
 */
export default function EventsSectionTabs() {
  const t = useTranslations("EventsPage.sections");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();
  const active = pathname.startsWith("/events/streams")
    ? "/events/streams"
    : "/events";

  return (
    <nav aria-label={t("label")} className="min-w-0">
      <CountSegmentedControl
        items={TABS.map((tab) => ({
          value: tab.href,
          label: (
            <span className="flex items-center gap-1.5 whitespace-nowrap">
              {tab.labelKey === "events" ? (
                <Activity className="h-4 w-4" />
              ) : (
                <EntityIcon kind="stream" className="h-4 w-4" />
              )}
              {t(tab.labelKey)}
            </span>
          ),
        }))}
        value={active}
        onChange={(next) => router.push(next)}
        variant="solid"
        className="max-w-full"
        layoutId="events-section-control"
      />
    </nav>
  );
}
