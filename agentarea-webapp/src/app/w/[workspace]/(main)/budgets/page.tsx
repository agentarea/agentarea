import { Suspense } from "react";
import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { BudgetsData } from "./components/BudgetsData";
import BudgetsSkeleton from "./components/BudgetsSkeleton";

export const metadata: Metadata = {
  title: "Budgets",
};

export default async function BudgetsPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Budgets" }],
      }}
      className="!p-0 lg:!overflow-hidden"
    >
      <Suspense fallback={<BudgetsSkeleton />}>
        <BudgetsData />
      </Suspense>
    </ContentBlock>
  );
}
