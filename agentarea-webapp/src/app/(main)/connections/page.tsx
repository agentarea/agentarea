import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput";
import { AddConnectionDropdown } from "../mcp-servers/components/AddConnectionDropdown";
import MCPHeaderTabs from "../mcp-servers/components/MCPHeaderTabs";
import MCPServersContent from "../mcp-servers/components/MCPServersContent";

export const metadata: Metadata = {
  title: "Connections",
};

export default async function ConnectionsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("MCPServersPage");
  const resolvedSearchParams = await searchParams;
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_mcp-servers")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
        controls: <AddConnectionDropdown />,
      }}
      subheader={
        <>
          <SearchInput urlParamName="search" urlPath="/connections" />
          <MCPHeaderTabs currentTab={tab} />
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
        <MCPServersContent searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
