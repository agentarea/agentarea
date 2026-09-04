import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Link from "next/link";
import { Settings } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import SearchInput from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import ProviderHeaderTabs from "./components/ProviderHeaderTabs";
import ProvidersData from "./components/ProvidersData";
import ProvidersSkeleton from "./components/ProvidersSkeleton";

export const metadata: Metadata = {
  title: "Provider Configs",
};

interface TasksPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ProviderConfigsPage({
  searchParams,
}: TasksPageProps) {
  const t = await getTranslations("Models");
  const resolvedSearchParams = await searchParams;
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
        breadcrumb: [{ label: t("title"), href: "/admin/provider-configs" }],
        description: t("description"),
        controls: (
          <Link href="/admin/provider-configs/create">
            <Button
              className="shrink-0"
              size="xs"
              data-test="new-config-button"
            >
              <Settings />
              {t("createButton")}
            </Button>
          </Link>
        ),
      }}
      subheader={
        <>
          <SearchInput
            urlParamName="search"
            urlPath="/admin/provider-configs"
          />
          <ProviderHeaderTabs currentTab={tab} />
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
