import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { PoliciesData } from "./components/PoliciesData";

export const metadata: Metadata = {
  title: "Policies",
};

export default async function PoliciesPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Policies" }],
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
          <PoliciesData />
        </Suspense>
      </div>
    </ContentBlock>
  );
}
