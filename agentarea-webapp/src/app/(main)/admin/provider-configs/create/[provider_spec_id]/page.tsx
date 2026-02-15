import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import ProviderConfigFormWrapper from "../components/ProviderConfigFormWrapper";
import { Button } from "@/components/ui/button";
import { getProviderSpec } from "@/lib/api";

interface CreateProviderConfigWithSpecPageProps {
  params: Promise<{ provider_spec_id: string }>;
}

export async function generateMetadata({ params }: CreateProviderConfigWithSpecPageProps): Promise<Metadata> {
  const { provider_spec_id } = await params;
  const t = await getTranslations("Metadata");
  try {
    const spec = await getProviderSpec(provider_spec_id);
    return {
      title: spec?.data?.name
        ? t("createProviderConfigForProvider", { providerName: spec.data.name })
        : t("createProviderConfig"),
    };
  } catch {
    return { title: t("createProviderConfig") };
  }
}

export default async function CreateProviderConfigWithSpecPage({
  params,
}: {
  params: Promise<{ provider_spec_id: string }>;
}) {
  const resolvedParams = await params;
  const { provider_spec_id } = resolvedParams;
  const t = await getTranslations("Models");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/admin/provider-configs" },
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
      <Suspense
        key={provider_spec_id}
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <ProviderConfigFormWrapper
          preselectedProviderId={provider_spec_id}
          isEdit={false}
        />
      </Suspense>
    </ContentBlock>
  );
}

