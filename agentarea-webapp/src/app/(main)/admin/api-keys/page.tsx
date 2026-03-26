import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import APIKeysContent from "./APIKeysContent";
import CreateAPIKeyButton from "./components/CreateAPIKeyButton";

export const metadata: Metadata = {
  title: "API Keys",
};

export default async function APIKeysPage() {
  const t = await getTranslations("APIKeysPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Admin", href: "/admin/provider-configs" },
          { label: t("title") },
        ],
        description: t("description"),
        controls: <CreateAPIKeyButton />,
      }}
    >
      <Suspense
        fallback={
          <div className="flex h-64 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <APIKeysContent />
      </Suspense>
    </ContentBlock>
  );
}
