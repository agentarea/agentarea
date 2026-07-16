import type { Metadata } from "next";
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
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Dashboard" }],
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
