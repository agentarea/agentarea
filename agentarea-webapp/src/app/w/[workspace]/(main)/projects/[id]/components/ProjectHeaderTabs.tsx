"use client";

import { useTranslations } from "next-intl";
import { FileText, Gauge, SlidersHorizontal } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";

const TABS = [
  { key: "", icon: Gauge, labelKey: "overview" },
  { key: "files", icon: FileText, labelKey: "files" },
  { key: "settings", icon: SlidersHorizontal, labelKey: "settings" },
] as const;

/**
 * Project detail navigation — the same solid segmented control as the agent
 * page: these entries switch the page's primary content, they don't filter it.
 */
export default function ProjectHeaderTabs({
  projectId,
}: {
  projectId: string;
}) {
  const t = useTranslations("ProjectsPage.sections");
  const pathname = useWorkspacePathname();
  const router = useWorkspaceRouter();
  const base = `/projects/${projectId}`;
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
        layoutId="project-section-control"
      />
    </nav>
  );
}
