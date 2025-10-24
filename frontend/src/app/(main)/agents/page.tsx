import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Link from "next/link";
import { Plus } from "lucide-react";
import AgentsContent from "@/app/(main)/agents/components/AgentsContent";
import AgentsHeaderTabs from "@/app/(main)/agents/components/AgentsHeaderTabs";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput/SearchInput";
import { Button } from "@/components/ui/button";

interface AgentsBrowsePageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function AgentsBrowsePage({
  searchParams,
}: AgentsBrowsePageProps) {
  const t = await getTranslations("AgentsPage");
  const resolvedSearchParams = await searchParams;
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_agents")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("browseAgents") }],
        description: t("mainDescriptionPage"),
        controls: (
          <Link href="/agents/create">
            <Button
              className="shrink-0 gap-2"
              size="xs"
              data-test="deploy-button"
            >
              <Plus className="h-5 w-5" />
              {t("deployNewAgent")}
            </Button>
          </Link>
        ),
      }}
      subheader={
        <>
          <SearchInput urlParamName="search" urlPath="/agents" />
          <AgentsHeaderTabs />
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
        <AgentsContent searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
