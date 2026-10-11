"use client";

import { useTranslations } from "next-intl";
import { Activity, FileText, Gauge, Package } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";

const TABS = [
  { key: "", icon: Gauge, labelKey: "overview" },
  { key: "events", icon: Activity, labelKey: "events" },
  { key: "files", icon: FileText, labelKey: "files" },
  { key: "artifacts", icon: Package, labelKey: "artifacts" },
] as const;

/**
 * Task detail navigation — the same solid segmented control as the agent,
 * trigger and project pages: these entries switch the page's primary content,
 * they don't filter it.
 */
export default function TaskSubheader({ taskId }: { taskId: string }) {
  const t = useTranslations("TasksPage.tabs");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();
  const base = `/tasks/${taskId}`;
  const activeTab =
    TABS.find((tab) =>
      tab.key
        ? pathname === `${base}/${tab.key}` ||
          pathname.startsWith(`${base}/${tab.key}/`)
        : pathname === base
    )?.key ?? "";

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
          };
        })}
        value={activeTab}
        onChange={(next) => router.push(next ? `${base}/${next}` : base)}
        variant="solid"
        className="max-w-full"
        layoutId="task-section-control"
      />
    </nav>
  );
}
