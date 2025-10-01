import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from 'next-intl/server';
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Settings } from "lucide-react";
import ProvidersData from "./components/ProvidersData";
import ProviderHeaderTabs from "./components/ProviderHeaderTabs";
import { cookies } from 'next/headers';

interface TasksPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ProviderConfigsPage({ searchParams }: TasksPageProps) {
  const t = await getTranslations("Models");
  const resolvedSearchParams = await searchParams;
  const searchQuery = typeof resolvedSearchParams.search === 'string' ? resolvedSearchParams.search : "";
  
  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get('tab_admin_provider-configs')?.value;
  const tab = typeof resolvedSearchParams.tab === 'string' ? resolvedSearchParams.tab : (cookieTab || "grid");

  return (
    <ContentBlock
        header={{
            breadcrumb: [
                {label: t("title"), href: "/admin/provider-configs"},
            ],
            description: t("description"),
            controls: (
                <Link href="/admin/provider-configs/create">
                    <Button className="shrink-0 gap-2" size="xs" data-test="new-config-button">
                        <Settings className="mr-2 h-4 w-4" />
                        {t("createButton")}
                    </Button>
                </Link>
            )
        }}
      className="p-0"
    >
      <div className="flex flex-col h-full">
        <div className="bg-white dark:bg-zinc-800 px-4 border-b border-zinc-200 dark:border-zinc-700 flex items-center justify-between gap-3 md:gap-10">
            <SearchInput 
                urlParamName="search"
                urlPath="/admin/provider-configs"
            />
            <ProviderHeaderTabs />
        </div>
        <div className="px-4 py-5 overflow-auto h-full">
          <Suspense 
            key={`${searchQuery}-${tab}`}
            fallback={
              <div className="flex items-center justify-center h-32">
                <LoadingSpinner />
              </div>
            }
          >
            <ProvidersData searchQuery={searchQuery} viewMode={tab} />
          </Suspense>
        </div>
      </div>
    </ContentBlock>
  );
}