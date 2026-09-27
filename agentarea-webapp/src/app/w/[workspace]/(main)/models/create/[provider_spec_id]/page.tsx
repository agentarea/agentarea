import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { FormSkeleton } from "@/components/Skeleton";
import ProviderConfigFormWrapper from "../components/ProviderConfigFormWrapper";
import { Button } from "@/components/ui/button";
import { getViewerCapabilities } from "@/lib/workspace-context";

export const metadata: Metadata = {
  title: "Create Provider Config",
};

export default async function CreateProviderConfigWithSpecPage({
  params,
}: {
  params: Promise<{ provider_spec_id: string }>;
}) {
  const [{ provider_spec_id }, t, { canAdminister }] = await Promise.all([
    params,
    getTranslations("Models"),
    getViewerCapabilities(),
  ]);

  if (!canAdminister) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("title"), href: "/models" },
            { label: t("createConfig") },
          ],
        }}
      >
        <AdminOnlyState what="providerConfigs" />
      </ContentBlock>
    );
  }

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/models" },
          { label: t("createConfig") },
        ],
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button size="xs" type="submit" form="provider-config-form">
              {t("createConfig") as string}
            </Button>
          </div>
        ),
      }}
    >
      <Suspense key={provider_spec_id} fallback={<FormSkeleton />}>
        <ProviderConfigFormWrapper
          preselectedProviderId={provider_spec_id}
          isEdit={false}
        />
      </Suspense>
    </ContentBlock>
  );
}

