import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import FormError from "@/components/FormError/FormError";
import SearchInput from "@/components/SearchInput";
import { AddConnectionDropdown } from "./components/AddConnectionDropdown";
import MCPHeaderTabs from "./components/MCPHeaderTabs";
import MCPServersContent from "./components/MCPServersContent";
import MCPSkeleton, { mcpSkeletonColumns } from "./components/MCPSkeleton";

export const metadata: Metadata = {
  title: "Connections",
};

export default async function MCPServersPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("MCPServersPage");
  const resolvedSearchParams = await searchParams;

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_connections")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";
  // An OAuth callback that could not resolve its connection lands here via `/`.
  const oauthError =
    resolvedSearchParams.oauth === "error"
      ? typeof resolvedSearchParams.reason === "string"
        ? resolvedSearchParams.reason
        : "unknown"
      : null;
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
      {oauthError && (
        <FormError className="mb-4">
          {t("instanceDetail.oauth.connectError", { reason: oauthError })}
        </FormError>
      )}
      <Suspense
        key={`${searchQuery}-${tab}`}
        fallback={
          <div id="my-connections">
            <MCPSkeleton
              viewMode={tab}
              columns={mcpSkeletonColumns(t)}
              headerLabel={t("myConnections")}
            />
          </div>
        }
      >
        <MCPServersContent searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
