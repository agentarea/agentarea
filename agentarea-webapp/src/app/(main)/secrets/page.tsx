import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { SecretsData } from "./components/SecretsData";

export const metadata: Metadata = {
  title: "Secrets",
};

export default async function SecretsPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Secrets" }],
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
          <SecretsData />
        </Suspense>
      </div>
    </ContentBlock>
  );
}
