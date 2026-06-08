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
      {/* No extra padding wrapper here — ContentBlock already supplies the
          page gutter, and the secrets list bleeds it edge-to-edge. */}
      <Suspense
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <SecretsData />
      </Suspense>
    </ContentBlock>
  );
}
