import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getViewerCapabilities } from "@/lib/workspace-context";
import ModelsHeaderControls from "./components/ModelsHeaderControls";
import ModelsSubheader from "./components/ModelsSubheader";
import ProvidersData from "./components/ProvidersData";
import ProvidersSkeleton from "./components/ProvidersSkeleton";

export const metadata: Metadata = {
  title: "Models",
};

interface TasksPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ProviderConfigsPage({
  searchParams,
}: TasksPageProps) {
  const [t, resolvedSearchParams, { canAdminister }] = await Promise.all([
    getTranslations("Models"),
    searchParams,
    getViewerCapabilities(),
  ]);
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  // Read tab from URL or fall back to the cookie HeaderTabs writes for /models
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_models")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";

  const configColumns = [
    { header: t("table.name"), barClassName: "h-4 w-32" },
    { header: t("table.provider"), barClassName: "h-4 w-24" },
    { header: t("table.models"), barClassName: "h-5 w-28 rounded-full" },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title"), href: "/models" }],
        description: t("description"),
        controls: <ModelsHeaderControls canAdminister={canAdminister} />,
      }}
      subheader={<ModelsSubheader path="/models" currentTab={tab} />}
    >
      <Suspense
        key={searchQuery}
        fallback={
          <ProvidersSkeleton
            viewMode={tab}
            configsLabel={t("providerConfigsSection")}
            configColumns={configColumns}
          />
        }
      >
        <ProvidersData searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
