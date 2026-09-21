"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, Gauge, List, Pencil } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";

const TABS = [
  { key: "", icon: Gauge, labelKey: "overview" },
  { key: "executions", icon: List, labelKey: "executions", counted: true },
  { key: "metrics", icon: BarChart3, labelKey: "metrics" },
  { key: "edit", icon: Pencil, labelKey: "edit" },
] as const;

/**
 * Trigger detail navigation. Same solid segmented control as the agent detail
 * page: these entries switch the page's primary content. Editing is one of
 * them — an underlined text link made the only way to change a saved
 * automation the least visible thing on the page.
 */
export default function TriggerDetailTabs({
  triggerId,
  executionCount,
}: {
  triggerId: string;
  /** Total runs, shown next to the Executions tab. */
  executionCount?: number;
}) {
  const t = useTranslations("TriggersPage.detail");
  const pathname = usePathname();
  const router = useRouter();

  const hrefFor = (key: string) =>
    key ? `/triggers/${triggerId}/${key}` : `/triggers/${triggerId}`;

  const activeTab =
    TABS.find((tab) => {
      const href = hrefFor(tab.key);
      return tab.key
        ? pathname === href || pathname.startsWith(`${href}/`)
        : pathname === href;
    })?.key ?? "";

  return (
    <nav aria-label="Trigger sections" className="min-w-0 flex-1">
      <CountSegmentedControl
        items={TABS.map((tab) => {
          const Icon = tab.icon;
          const count =
            "counted" in tab && tab.counted && executionCount
              ? executionCount
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
        onChange={(next) => router.push(hrefFor(next))}
        variant="solid"
        className="max-w-full"
        layoutId="trigger-section-control"
      />
    </nav>
  );
}
