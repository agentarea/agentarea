"use client";

import { useTranslations } from "next-intl";
import { Gauge, SquareTerminal, Wrench } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";

const TABS = [
  { key: "", icon: Gauge, labelKey: "overview" },
  { key: "tools", icon: Wrench, labelKey: "tools" },
  { key: "runner", icon: SquareTerminal, labelKey: "runner" },
] as const;

/** Harness detail navigation: the same solid segmented control as a connection's. */
export default function ClientDetailTabs({
  basePath,
  toolCount,
  withRunner,
}: {
  basePath: string;
  /** What the harness serves, shown next to the Tools tab. */
  toolCount: number;
  /** Only a Codex or Claude Code harness has a runner. */
  withRunner: boolean;
}) {
  const t = useTranslations("ClientsPage.tabs");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();

  const hrefFor = (key: string) => (key ? `${basePath}/${key}` : basePath);
  const tabs = TABS.filter((tab) => withRunner || tab.key !== "runner");
  const activeTab =
    tabs.find((tab) => {
      const href = hrefFor(tab.key);
      return tab.key
        ? pathname === href || pathname.startsWith(`${href}/`)
        : pathname === href;
    })?.key ?? "";

  return (
    <nav aria-label={t("label")} className="min-w-0 flex-1">
      <CountSegmentedControl
        items={tabs.map((tab) => {
          const Icon = tab.icon;
          return {
            value: tab.key,
            label: (
              <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Icon className="h-4 w-4" strokeWidth={1.8} />
                {t(tab.labelKey)}
              </span>
            ),
            count: tab.key === "tools" && toolCount ? toolCount : undefined,
          };
        })}
        value={activeTab}
        onChange={(next) => router.push(hrefFor(next))}
        variant="solid"
        itemClassName="max-md:min-h-11"
        className="max-w-full"
        layoutId="client-section-control"
      />
    </nav>
  );
}
