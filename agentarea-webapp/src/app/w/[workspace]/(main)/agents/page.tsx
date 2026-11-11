import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Plus } from "lucide-react";
import { AGENT_COLUMNS } from "@/app/w/[workspace]/(main)/agents/components/agentColumns";
import AgentsContent from "@/app/w/[workspace]/(main)/agents/components/AgentsContent";
import AgentsSkeleton from "@/app/w/[workspace]/(main)/agents/components/AgentsSkeleton";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { readUiPrefs } from "@/lib/ui-prefs-server";

export const metadata: Metadata = {
  title: "Agents",
};

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

  // Read tab from URL, else the remembered view
  const uiPrefs = await readUiPrefs();
  const cookieTab = uiPrefs.views["tab_agents"];
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";

  // Resolve table header labels here (the page has the translations); the
  // skeleton stays a sync component so it never re-suspends as a fallback.
  const skeletonColumns = AGENT_COLUMNS.map((column) => ({
    header: t(column.labelKey),
    cellClassName: column.cellClassName,
    barClassName: column.barClassName,
  }));

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("browseAgents") }],
        description: t("mainDescriptionPage"),
        controls: (
          <Button
            asChild
            className="shrink-0"
            size="xs"
            data-test="deploy-button"
          >
            <Link href="/agents/create">
              <Plus />
              {t("deployNewAgent")}
            </Link>
          </Button>
        ),
      }}
      subheader={
        <SubheaderToolbar
          search={<SearchInput urlParamName="search" urlPath="/agents" />}
          controls={<ViewModeTabs currentTab={tab} />}
        />
      }
    >
      <Suspense
        key={`${searchQuery}-${tab}`}
        fallback={<AgentsSkeleton viewMode={tab} columns={skeletonColumns} />}
      >
        <AgentsContent searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
