"use client";

import { useTranslations } from "next-intl";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Brain, Store } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";

const TABS = [
  { href: "/models", icon: Brain, labelKey: "connected" },
  { href: "/models/specs", icon: Store, labelKey: "available", counted: true },
] as const;

/**
 * Connected models and the catalog of providers you could still add are two
 * pages, not one list with a footnote under it — the catalog is long enough
 * that it drowned the handful of providers actually in use.
 *
 * Solid segmented control, same as the explore type switcher: these entries
 * switch the page's primary content, not filter it.
 */
export default function ModelsSectionTabs({
  availableCount,
}: {
  availableCount?: number;
}) {
  const t = useTranslations("Models.sections");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();

  const activeTab =
    TABS.find((tab) => tab.href !== "/models" && pathname.startsWith(tab.href))
      ?.href ?? "/models";

  return (
    <nav aria-label={t("label")} className="min-w-0">
      <CountSegmentedControl
        items={TABS.map((tab) => {
          const Icon = tab.icon;
          const count =
            "counted" in tab && tab.counted && availableCount
              ? availableCount
              : undefined;

          return {
            value: tab.href,
            label: (
              <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Icon className="h-4 w-4" />
                {t(tab.labelKey)}
              </span>
            ),
            count,
          };
        })}
        value={activeTab}
        onChange={(next) => router.push(next)}
        variant="solid"
        layoutId="models-section-control"
      />
    </nav>
  );
}
