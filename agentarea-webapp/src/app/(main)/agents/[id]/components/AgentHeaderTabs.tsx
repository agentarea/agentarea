"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  CreditCard,
  Gauge,
  List,
  Network,
  Play,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";

const TABS = [
  { key: "", icon: Gauge, labelKey: "overview" },
  { key: "new-task", icon: Play, labelKey: "createTask" },
  { key: "tasks", icon: List, labelKey: "currentTasks", counted: true },
  { key: "payments", icon: CreditCard, labelKey: "payments" },
  { key: "delegation", icon: Users, labelKey: "delegation" },
  { key: "settings", icon: SlidersHorizontal, labelKey: "settings" },
] as const;

/**
 * Agent detail navigation. It deliberately reuses the solid segmented control
 * from Explore: these entries switch the page's primary content, rather than
 * filtering the content already on the page.
 */
export default function AgentHeaderTabs({
  agentId,
  runningCount,
}: {
  agentId: string;
  /** Number of in-progress tasks, shown next to the Tasks tab. */
  runningCount?: number;
}) {
  const t = useTranslations("AgentsPage");
  const pathname = usePathname();
  const router = useRouter();
  const activeTab =
    TABS.find((tab) => {
      const href = tab.key
        ? `/agents/${agentId}/${tab.key}`
        : `/agents/${agentId}`;
      return tab.key
        ? pathname === href || pathname.startsWith(`${href}/`)
        : pathname === href;
    })?.key ?? "";

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5">
      <nav aria-label="Agent sections" className="min-w-0 flex-1">
        <CountSegmentedControl
          items={TABS.map((tab) => {
            const Icon = tab.icon;
            const count =
              "counted" in tab && tab.counted && runningCount
                ? runningCount
                : undefined;

            return {
              value: tab.key,
              label: (
                <span className="flex items-center gap-1.5 whitespace-nowrap">
                  <Icon className="h-4 w-4" strokeWidth={1.8} />
                  {t(tab.labelKey)}
                </span>
              ),
              count,
            };
          })}
          value={activeTab}
          onChange={(next) => {
            const href = next
              ? `/agents/${agentId}/${next}`
              : `/agents/${agentId}`;
            router.push(href);
          }}
          variant="solid"
          className="max-w-full"
          layoutId="agent-section-control"
        />
      </nav>

      <div className="mx-1 hidden h-[18px] w-px shrink-0 bg-border md:block" />
      <Link
        href="/network"
        className="hidden h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] text-foreground/80 transition-colors hover:bg-muted/60 md:inline-flex"
      >
        <Network
          className="h-[15px] w-[15px] text-muted-foreground"
          strokeWidth={1.8}
        />
        {t("activity")}
      </Link>
    </div>
  );
}
