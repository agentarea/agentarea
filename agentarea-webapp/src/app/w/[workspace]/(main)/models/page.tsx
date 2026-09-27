import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Link from "@/components/WorkspaceLink";
import { Settings } from "lucide-react";
import { AdminOnlyHint } from "@/components/AdminOnlyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import SearchInput from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import { getViewerCapabilities } from "@/lib/workspace-context";
import ModelsSectionTabs from "./components/ModelsSectionTabs";
import ProviderHeaderTabs from "./components/ProviderHeaderTabs";
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

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_admin_provider-configs")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";

  const configColumns = [
    { header: t("table.name"), barClassName: "h-4 w-32" },
    { header: t("table.provider"), barClassName: "h-4 w-24" },
    { header: t("table.models"), barClassName: "h-5 w-28 rounded-full" },
  ];
  const specColumns = [
    { header: t("table.name"), barClassName: "h-4 w-32" },
    { header: t("table.description"), cellClassName: "max-w-[300px]", barClassName: "h-3 w-48" },
    { header: t("table.models"), barClassName: "h-5 w-28 rounded-full" },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title"), href: "/models" }],
        description: t("description"),
        controls: canAdminister ? (
          <Link href="/models/create">
            <Button
              className="shrink-0"
              size="xs"
              data-test="new-config-button"
            >
              <Settings />
              {t("createButton")}
            </Button>
          </Link>
        ) : (
          <div className="flex items-center gap-2">
            <AdminOnlyHint action="manageProvider" />
            <Button
              className="shrink-0"
              size="xs"
              data-test="new-config-button"
              disabled
            >
              <Settings />
              {t("createButton")}
            </Button>
          </div>
        ),
      }}
      subheader={
        <>
          <ModelsSectionTabs />
          <div className="flex flex-1 items-center justify-end gap-3">
            <SearchInput urlParamName="search" urlPath="/models" />
            <ProviderHeaderTabs currentTab={tab} />
          </div>
        </>
      }
    >
      <Suspense
        key={searchQuery}
        fallback={
          <ProvidersSkeleton
            viewMode={tab}
            configsLabel={t("providerConfigsSection")}
            specsLabel={t("providerSpecsSection")}
            configColumns={configColumns}
            specColumns={specColumns}
          />
        }
      >
        <ProvidersData searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
