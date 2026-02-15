import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import ProviderConfigFormWrapper from "../../create/components/ProviderConfigFormWrapper";
import { Button } from "@/components/ui/button";
import { getProviderConfig } from "@/lib/api";

interface EditProviderConfigPageProps {
  params: Promise<{ providerConfigId: string }>;
}

export async function generateMetadata({ params }: EditProviderConfigPageProps): Promise<Metadata> {
  const { providerConfigId } = await params;
  const t = await getTranslations("Metadata");
  try {
    const config = await getProviderConfig(providerConfigId);
    return {
      title: config?.name
        ? t("editProviderConfig", { configName: config.name })
        : t("editProviderConfig", { configName: "Config" }),
    };
  } catch {
    return { title: t("editProviderConfig", { configName: "Config" }) };
  }
}

export default async function EditProviderConfigPage({
  params,
}: {
  params: Promise<{ providerConfigId: string }>;
}) {
  const resolvedParams = await params;
  const { providerConfigId } = resolvedParams;
  const t = await getTranslations("Models");
  const tCommon = await getTranslations("Common");

  // Load provider config to verify it exists and get name for breadcrumb
  let providerConfig;
  try {
    providerConfig = await getProviderConfig(providerConfigId);
  } catch (error) {
    console.error("Failed to load provider config:", error);
    notFound();
  }

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/admin/provider-configs" },
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
      <Suspense
        key={providerConfigId}
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <ProviderConfigFormWrapper
          preselectedProviderId={providerConfigId}
          isEdit={true}
        />
      </Suspense>
    </ContentBlock>
  );
}

