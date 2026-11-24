"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Activity, Cpu, Shapes } from "lucide-react";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import ToolbarSelect from "@/components/ToolbarSelect";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";
import { feedHref, parseFeedState, type FeedState } from "@/lib/eventFeed";
import { useResultFilter } from "../../components/feed/useResultFilter";

/**
 * A stream's sections, the same solid control as a trigger's or an agent's:
 * they switch the page's content. The events tab also carries the feed's
 * result filter on the right. The platform's stream has one fixed source with
 * nothing to show or change, so no sources tab; processors show only when the
 * stream has some; and with a lone tab there is no switch at all.
 */
export default function StreamDetailTabs({
  streamId,
  basePath,
  platform,
  sourceCount,
  sourcesFailing,
  processorCount,
}: {
  streamId: string;
  /** The page's own path; the stream's (`/events/{id}`) unless given. */
  basePath?: string;
  platform: boolean;
  sourceCount?: number;
  /** A source's last poll failed: the tab carries the failed glyph. */
  sourcesFailing: boolean;
  processorCount?: number;
}) {
  const t = useTranslations("EventsPage.streamPage");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  const base = basePath ?? `/events/${streamId}`;
  const tabs = [
    { href: base, icon: Activity, label: t("events") },
    ...(platform
      ? []
      : [
          {
            href: `${base}/sources`,
            icon: Shapes,
            label: t("sources"),
            count: sourceCount,
            failing: sourcesFailing,
          },
        ]),
    ...(processorCount
      ? [
          {
            href: `${base}/processors`,
            icon: Cpu,
            label: t("processors"),
            count: processorCount,
          },
        ]
      : []),
  ];
  const active =
    tabs.find((tab) => tab.href !== base && pathname.startsWith(tab.href))
      ?.href ?? base;

  const state = parseFeedState(Object.fromEntries(searchParams.entries()));
  const go = (patch: Partial<FeedState>) =>
    router.push(
      feedHref(
        state,
        { ...patch, event: undefined, before: undefined },
        {
          base,
          pinned: ["stream"],
        }
      ),
      { scroll: false }
    );
  const resultFilter = useResultFilter(state, go);

  return (
    <SubheaderToolbar
      categories={
        tabs.length > 1 && (
          <nav aria-label={t("label")} className="min-w-0">
            <CountSegmentedControl
              items={tabs.map((tab) => {
                const Icon = tab.icon;
                return {
                  value: tab.href,
                  label: (
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                      <Icon className="h-4 w-4" strokeWidth={1.8} />
                      {tab.label}
                      {"failing" in tab && tab.failing && (
                        <StatusIndicator
                          size="sm"
                          kind="failed"
                          aria-label={t("pollFailed")}
                        />
                      )}
                    </span>
                  ),
                  count: tab.count || undefined,
                };
              })}
              value={active}
              onChange={(href) => router.push(href)}
              variant="solid"
              className="max-w-full"
              layoutId="stream-section-control"
            />
          </nav>
        )
      }
      controls={
        active === base ? <ToolbarSelect<string> {...resultFilter} /> : null
      }
    />
  );
}
