import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import APIKeyForm from "./components/APIKeyForm";

export const metadata: Metadata = {
  title: "Create API Key",
};

export default async function CreateAPIKeyPage() {
  const t = await getTranslations("APIKeysPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Admin", href: "/admin/provider-configs" },
          { label: t("title"), href: "/admin/api-keys" },
          { label: t("create.title") },
        ],
        description: t("create.description"),
        controls: (
          <Button size="xs" type="submit" form="api-key-form">
            {t("create.createButton")}
          </Button>
        ),
      }}
    >
      <Suspense
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <APIKeyForm />
      </Suspense>
    </ContentBlock>
  );
}
