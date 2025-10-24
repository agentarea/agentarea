import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Link from "next/link";
import { Settings } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import ProviderHeaderTabs from "./components/ProviderHeaderTabs";
import ProvidersData from "./components/ProvidersData";

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

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title"), href: "/admin/provider-configs" }],
        description: t("description"),
        controls: (
          <Link href="/admin/provider-configs/create">
            <Button
              className="shrink-0 gap-2"
              size="xs"
              data-test="new-config-button"
            >
              <Settings className="mr-2 h-4 w-4" />
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
          <ProviderHeaderTabs />
        </>
      }
    >
      <Suspense
        key={`${searchQuery}-${tab}`}
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <ProvidersData searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
