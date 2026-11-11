import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import FormError from "@/components/FormError/FormError";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { getCatalogItem } from "@/lib/api";
import { parseCatalogSource } from "@/lib/catalog-connections";
import { readUiPrefs } from "@/lib/ui-prefs-server";
import {
  normalize,
  type RegistryItem,
} from "../bundles/components/catalog-data";
import { AddConnectionDropdown } from "./components/AddConnectionDropdown";
import ConnectionsDisplayMenu from "./components/ConnectionsDisplayMenu";
import ConnectionsFilterSection from "./components/ConnectionsFilterSection";
import MCPServersContent from "./components/MCPServersContent";
import MCPSkeleton, { mcpSkeletonColumns } from "./components/MCPSkeleton";
import { parseGroupBy, parseListFilter } from "./list-sections";

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

  // Read tab from URL, else the remembered view
  const uiPrefs = await readUiPrefs();
  const cookieTab = uiPrefs.views["tab_connections"];
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";
  const filter = parseListFilter(resolvedSearchParams.filter);
  const groupBy = parseGroupBy(resolvedSearchParams.group);
  // Opened from a catalog item with several connections: only those.
  const source = parseCatalogSource(resolvedSearchParams.source);
  const sourceItem = source ? (await getCatalogItem(source)).data : null;
  const sourceName = sourceItem
    ? normalize("connections", sourceItem as RegistryItem).title
    : source;
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
        breadcrumb: source
          ? [
              { label: t("title"), href: "/connections" },
              {
                label: t("sourceFilter", { name: sourceName ?? "" }),
              },
            ]
          : [{ label: t("title") }],
        description: t("description"),
        controls: <AddConnectionDropdown />,
      }}
      subheader={
        <SubheaderToolbar
          categories={
            <Suspense fallback={<div className="h-7" />}>
              <ConnectionsFilterSection
                currentFilter={filter}
                source={source}
              />
            </Suspense>
          }
          search={<SearchInput urlParamName="search" urlPath="/connections" />}
          controls={
            <>
              <ConnectionsDisplayMenu currentGroup={groupBy} />
              <ViewModeTabs currentTab={tab} />
            </>
          }
        />
      }
    >
      {oauthError && (
        <FormError className="mb-4">
          {t("instanceDetail.oauth.connectError", { reason: oauthError })}
        </FormError>
      )}
      <Suspense
        key={`${searchQuery}-${tab}-${filter}-${groupBy}-${source ?? ""}`}
        fallback={
          <div id="my-connections">
            <MCPSkeleton viewMode={tab} columns={mcpSkeletonColumns(t)} />
          </div>
        }
      >
        <MCPServersContent
          searchQuery={searchQuery}
          viewMode={tab}
          filter={filter}
          groupBy={groupBy}
          source={source}
        />
      </Suspense>
    </ContentBlock>
  );
}
