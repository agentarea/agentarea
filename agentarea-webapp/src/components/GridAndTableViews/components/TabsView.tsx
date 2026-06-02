"use client";

import { useTranslations } from "next-intl";
import HeaderTabs from "@/components/HeaderTabs";
import { TabsWithNavigation } from "./TabsWithNavigation";

export default function TabsView({
  searchParams,
  leftComponent,
  routeChange,
  children,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
  emptyState?: React.ReactNode;
  leftComponent?: React.ReactNode;
  routeChange: string;
  children: React.ReactNode;
}) {
  const t = useTranslations("Common");

  const tab = searchParams?.tab;
  const activeTab =
    typeof tab === "string" && (tab === "grid" || tab === "table")
      ? tab
      : "grid";

  return (
    <TabsWithNavigation activeTab={activeTab} routeChange={routeChange}>
      <div className="mb-3 flex flex-row items-center justify-between gap-[10px]">
        <div className="flex flex-1 flex-row items-center gap-[10px]">
          {leftComponent}
        </div>

        <div>
          <HeaderTabs
            paramName="tab"
            defaultTab="grid"
            currentTab={activeTab}
            tabs={[
              { value: "table", label: t("table") },
              { value: "grid", label: t("grid") },
            ]}
          />
        </div>
      </div>

      {children}
    </TabsWithNavigation>
  );
}
