"use client";

import { useTranslations } from "next-intl";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Gauge, ScrollText, Wrench } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";

const TABS = [
  { key: "", icon: Gauge, labelKey: "overview" },
  { key: "tools", icon: Wrench, labelKey: "tools", counted: true },
  { key: "activity", icon: ScrollText, labelKey: "activity" },
] as const;

/**
 * Connection detail navigation: the same solid segmented control as the agent
 * and automation detail pages.
 */
export default function ConnectionDetailTabs({
  instanceId,
  toolCount,
}: {
  instanceId: string;
  /** Discovered tools, shown next to the Tools tab. */
  toolCount?: number;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.tabs");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();

  const hrefFor = (key: string) =>
    key ? `/connections/${instanceId}/${key}` : `/connections/${instanceId}`;

  const activeTab =
    TABS.find((tab) => {
      const href = hrefFor(tab.key);
      return tab.key
        ? pathname === href || pathname.startsWith(`${href}/`)
        : pathname === href;
    })?.key ?? "";

  return (
    <nav aria-label={t("label")} className="min-w-0 flex-1">
      <CountSegmentedControl
        items={TABS.map((tab) => {
          const Icon = tab.icon;
          return {
            value: tab.key,
            label: (
              <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Icon className="h-4 w-4" strokeWidth={1.8} />
                {t(tab.labelKey)}
              </span>
            ),
            count:
              "counted" in tab && tab.counted && toolCount ? toolCount : undefined,
          };
        })}
        value={activeTab}
        onChange={(next) => router.push(hrefFor(next))}
        variant="solid"
        itemClassName="max-md:min-h-11"
        className="max-w-full"
        layoutId="connection-section-control"
      />
    </nav>
  );
}
