"use client";

import { useTranslations } from "next-intl";
import { Gauge, History, ListChecks } from "lucide-react";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";

const TABS = [
  { key: "", icon: Gauge, labelKey: "overview" },
  { key: "tasks", icon: ListChecks, labelKey: "tasks" },
  { key: "activity", icon: History, labelKey: "activity", adminOnly: true },
] as const;

/** Member detail navigation, the same solid control as the trigger detail. */
export default function MemberDetailTabs({
  basePath,
  showActivity,
}: {
  basePath: string;
  /** The audit trail is admin-only; members don't get a tab that 403s. */
  showActivity: boolean;
}) {
  const t = useTranslations("MembersPage.detail");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();

  const tabs = TABS.filter(
    (tab) => !("adminOnly" in tab && tab.adminOnly) || showActivity
  );
  const hrefFor = (key: string) => (key ? `${basePath}/${key}` : basePath);
  const activeTab =
    tabs.find((tab) => {
      const href = hrefFor(tab.key);
      return tab.key
        ? pathname === href || pathname.startsWith(`${href}/`)
        : pathname === href;
    })?.key ?? "";

  return (
    <SubheaderToolbar
      categories={
        <nav aria-label={t("sections")} className="min-w-0">
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
              };
            })}
            value={activeTab}
            onChange={(next) => router.push(hrefFor(next))}
            variant="solid"
            className="max-w-full"
            layoutId="member-section-control"
          />
        </nav>
      }
    />
  );
}
