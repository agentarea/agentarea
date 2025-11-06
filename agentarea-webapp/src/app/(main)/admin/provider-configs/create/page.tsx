import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import ProviderConfigFormWrapper from "./components/ProviderConfigFormWrapper";
import { Button } from "@/components/ui/button";
import { getProviderConfig, getProviderSpec } from "@/lib/api";

export default async function CreateProviderConfigPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const resolvedSearchParams = await searchParams;
  const t = await getTranslations("Models");
  const tCommon = await getTranslations("Common");

  // Get the provider_spec_id from query params if provided
  const preselectedProviderId =
    typeof resolvedSearchParams.provider_spec_id === "string"
      ? resolvedSearchParams.provider_spec_id
      : undefined;

  // Check if this is edit mode
  const isEdit = resolvedSearchParams.isEdit === "true";

  // Load provider config name for breadcrumb in edit mode
  let providerConfigName: string | undefined;
  if (isEdit && preselectedProviderId) {
    try {
      const configResponse = await getProviderConfig(preselectedProviderId);
      providerConfigName = configResponse?.name;
    } catch (error) {
      console.error("Failed to load provider config name:", error);
    }
  }

  // Load provider spec name for breadcrumb in create mode
  let providerSpecName: string | undefined;
  if (!isEdit && preselectedProviderId) {
    try {
      const specResponse = await getProviderSpec(preselectedProviderId);
      providerSpecName = specResponse?.data?.name;
    } catch (error) {
      console.error("Failed to load provider spec name:", error);
    }
  }

  return (
    <ContentBlock
      header={{
        breadcrumb: isEdit
          ? [
              { label: t("title"), href: "/admin/provider-configs" },
              { label: providerConfigName ? `${tCommon("edit")} ${providerConfigName}` : tCommon("edit") },
            ]
          : [
              { label: t("title"), href: "/admin/provider-configs" },
              { label: providerSpecName || t("createConfig") },
            ],
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button size="xs" type="submit" form="provider-config-form">
              {isEdit ? (tCommon("saveChanges") as string) : (t("createConfig") as string)}
            </Button>
          </div>
        ),
      }}
    >
      <Suspense
        key={`${preselectedProviderId}-${isEdit}`}
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <ProviderConfigFormWrapper
          preselectedProviderId={preselectedProviderId}
          isEdit={isEdit}
        />
      </Suspense>
    </ContentBlock>
  );
}
