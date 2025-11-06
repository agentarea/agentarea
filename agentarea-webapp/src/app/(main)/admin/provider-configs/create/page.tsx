import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import ProviderConfigFormWrapper from "./components/ProviderConfigFormWrapper";
import { Button } from "@/components/ui/button";
import { getProviderSpec } from "@/lib/api";

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

  // If provider_spec_id is provided, redirect to the dynamic route
  if (preselectedProviderId) {
    redirect(`/admin/provider-configs/create/${preselectedProviderId}`);
  }

  // Load provider spec name for breadcrumb (if provider_spec_id is provided)
  let providerSpecName: string | undefined;
  if (preselectedProviderId) {
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
        breadcrumb: [
          { label: t("title"), href: "/admin/provider-configs" },
          { label: providerSpecName || t("createConfig") },
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
      <Suspense
        key={preselectedProviderId || "create"}
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <ProviderConfigFormWrapper
          preselectedProviderId={preselectedProviderId}
          isEdit={false}
        />
      </Suspense>
    </ContentBlock>
  );
}
