import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { FormSkeleton } from "@/components/Skeleton";
import { Button } from "@/components/ui/button";
import { getProviderConfig } from "@/lib/api";
import { notFoundOnApi404 } from "@/lib/server-resource";
import { getViewerCapabilities } from "@/lib/workspace-context";
import ProviderConfigFormWrapper from "../../create/components/ProviderConfigFormWrapper";

export const metadata: Metadata = {
  title: "Edit Provider Config",
};

export default async function EditProviderConfigPage({
  params,
}: {
  params: Promise<{ providerConfigId: string }>;
}) {
  const [{ providerConfigId }, t, tCommon, { canAdminister }] =
    await Promise.all([
      params,
      getTranslations("Models"),
      getTranslations("Common"),
      getViewerCapabilities(),
    ]);

  if (!canAdminister) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("title"), href: "/models" },
            { label: tCommon("edit") },
          ],
        }}
      >
        <AdminOnlyState what="providerConfigs" />
      </ContentBlock>
    );
  }

  // Load provider config to verify it exists and get name for breadcrumb
  let providerConfig;
  try {
    providerConfig = await getProviderConfig(providerConfigId);
  } catch (error) {
    console.error("Failed to load provider config:", error);
    notFoundOnApi404(error);
    throw error;
  }

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/models" },
          {
            label: providerConfig?.name
              ? `${tCommon("edit")} ${providerConfig.name}`
              : tCommon("edit"),
          },
        ],
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button size="xs" type="submit" form="provider-config-form">
              {tCommon("saveChanges") as string}
            </Button>
          </div>
        ),
      }}
    >
      <Suspense key={providerConfigId} fallback={<FormSkeleton />}>
        <ProviderConfigFormWrapper
          preselectedProviderId={providerConfigId}
          isEdit={true}
        />
      </Suspense>
    </ContentBlock>
  );
}
