import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { DashboardData } from "./components/DashboardData";
import DashboardSkeleton from "./components/DashboardSkeleton";

export const metadata: Metadata = {
  title: "Dashboard",
};

export default async function DashboardPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Dashboard" }],
      }}
    >
      <div className="main-content">
        <Suspense fallback={<DashboardSkeleton />}>
          <DashboardData />
        </Suspense>
      </div>
    </ContentBlock>
  );
}
