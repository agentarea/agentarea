import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { DashboardData } from "./components/DashboardData";

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
        <Suspense
          fallback={
            <div className="flex h-32 items-center justify-center">
              <LoadingSpinner />
            </div>
          }
        >
          <DashboardData />
        </Suspense>
      </div>
    </ContentBlock>
  );
}
