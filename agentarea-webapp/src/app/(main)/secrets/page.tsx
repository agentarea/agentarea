import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { SecretsData } from "./components/SecretsData";
import SecretsSkeleton from "./components/SecretsSkeleton";

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
        <Suspense fallback={<SecretsSkeleton />}>
          <SecretsData />
        </Suspense>
      </div>
    </ContentBlock>
  );
}
