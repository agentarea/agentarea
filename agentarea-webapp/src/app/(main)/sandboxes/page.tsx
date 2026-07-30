import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listSandboxesAction } from "./actions";
import SandboxesClient from "./SandboxesClient";

export const metadata: Metadata = {
  title: "Sandboxes",
};

interface SandboxesPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function SandboxesPage({
  searchParams,
}: SandboxesPageProps) {
  const t = await getTranslations("SandboxesPage");
  const resolvedSearchParams = await searchParams;
  const result = await listSandboxesAction();

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
    >
      <SandboxesClient
        initialData={result.data}
        initialError={result.error}
        searchParams={{
          ...resolvedSearchParams,
          tab: resolvedSearchParams.tab ?? "table",
        }}
      />
    </ContentBlock>
  );
}
