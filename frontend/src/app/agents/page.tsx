import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Plus } from "lucide-react";
import AgentsContent from "@/app/agents/components/AgentsContent";
import SearchInput from "@/components/SearchInput/SearchInput";
import AgentsHeaderTabs from "@/app/agents/components/AgentsHeaderTabs";
import { cookies } from 'next/headers';

interface AgentsBrowsePageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function AgentsBrowsePage({ searchParams }: AgentsBrowsePageProps) {
  const t = await getTranslations("Agent");
  const resolvedSearchParams = await searchParams;
  const searchQuery = typeof resolvedSearchParams.search === 'string' ? resolvedSearchParams.search : "";
  
  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get('tab_agents')?.value;
  const tab = typeof resolvedSearchParams.tab === 'string' ? resolvedSearchParams.tab : (cookieTab || "grid");

  return (
    <ContentBlock 
      header={{
        breadcrumb: [
          {label: t("browseAgents")},
        ],
        description: t("mainDescriptionPage"),
        controls: (
          <Link href="/agents/create">
            <Button className="shrink-0 gap-2" size="xs" data-test="deploy-button">
              <Plus className="h-5 w-5" />
              {t("deployNewAgent")}
            </Button>
          </Link>
        )}}
        subheader={
          <>
            <SearchInput 
              urlParamName="search"
              urlPath="/agents"
            />
            <AgentsHeaderTabs />
          </>
          
        }
    >
      <Suspense
        key={`${searchQuery}-${tab}`}
        fallback={(
          <div className="flex items-center justify-center h-32">
            <LoadingSpinner />
          </div>
        )}
      >
        <AgentsContent searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}