import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { CreateSecretDialog } from "./components/CreateSecretDialog";
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
        controls: <CreateSecretDialog />,
      }}
    >
      <Suspense fallback={<SecretsSkeleton />}>
        <SecretsData />
      </Suspense>
    </ContentBlock>
  );
}
