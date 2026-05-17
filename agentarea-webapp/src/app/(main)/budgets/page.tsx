import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { BudgetsData } from "./components/BudgetsData";

export const metadata: Metadata = {
  title: "Budgets",
};

export default async function BudgetsPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Budgets" }],
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
          <BudgetsData />
        </Suspense>
      </div>
    </ContentBlock>
  );
}
