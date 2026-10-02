import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { CreateSecretDialog } from "./components/CreateSecretDialog";
import { SecretsData } from "./components/SecretsData";
import SecretsSkeleton from "./components/SecretsSkeleton";

export const metadata: Metadata = {
  title: "Secrets",
};

export default async function SecretsPage() {
  const t = await getTranslations("SecretsPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <CreateSecretDialog />,
      }}
    >
      <Suspense fallback={<SecretsSkeleton />}>
        <SecretsData />
      </Suspense>
    </ContentBlock>
  );
}
