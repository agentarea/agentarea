import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { DashboardData } from "./components/DashboardData";
import DashboardSkeleton from "./components/DashboardSkeleton";
// Hidden for now — the period picker returns once it drives scoped data.
// import { PeriodSelect } from "./components/PeriodSelect";

export const metadata: Metadata = {
  title: "Dashboard",
};

export default async function DashboardPage() {
  const t = await getTranslations("DashboardPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        // controls: <PeriodSelect />,
      }}
      className="!p-0 lg:!overflow-hidden"
    >
      <Suspense fallback={<DashboardSkeleton />}>
        <DashboardData />
      </Suspense>
    </ContentBlock>
  );
}
