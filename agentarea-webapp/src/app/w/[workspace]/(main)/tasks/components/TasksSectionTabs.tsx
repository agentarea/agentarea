"use client";

import { useTranslations } from "next-intl";
import { Bookmark, CalendarClock, History } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";

const TABS = [
  { href: "/tasks/upcoming", icon: CalendarClock, labelKey: "sectionExpected" },
  { href: "/tasks", icon: History, labelKey: "sectionRuns" },
  { href: "/tasks/saved", icon: Bookmark, labelKey: "sectionTemplates" },
] as const;

/** The Tasks page's sections: what will start, what started, and the templates to start from. */
export default function TasksSectionTabs() {
  const t = useTranslations("TasksPage");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();
  const active =
    TABS.find((tab) => tab.href !== "/tasks" && pathname.startsWith(tab.href))
      ?.href ?? "/tasks";

  return (
    <nav aria-label="Tasks sections" className="min-w-0">
      <CountSegmentedControl
        items={TABS.map((tab) => {
          const Icon = tab.icon;
          return {
            value: tab.href,
            label: (
              <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Icon className="h-4 w-4" strokeWidth={1.8} />
                {t(tab.labelKey)}
              </span>
            ),
          };
        })}
        value={active}
        onChange={(next) => router.push(next)}
        variant="solid"
        className="max-w-full"
        layoutId="tasks-section-control"
      />
    </nav>
  );
}
