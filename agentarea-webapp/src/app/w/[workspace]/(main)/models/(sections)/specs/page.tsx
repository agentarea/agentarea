import type { Metadata } from "next";
import type { ProviderSpecWithModelsResponse } from "@/api/client/types.gen";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import EmptyState from "@/components/EmptyState/EmptyState";
import { listProviderSpecsWithModels } from "@/lib/api";
import { getViewerCapabilities } from "@/lib/workspace-context";
import ProviderSpecsView from "../../components/ProviderSpecsView";
import ProvidersSkeleton from "../../components/ProvidersSkeleton";
import {
  MODELS_VIEW_COOKIE,
  resolveViewMode,
  type ModelsViewMode,
} from "../../components/viewMode";

export const metadata: Metadata = {
  title: "Providers",
};

type SearchParams = { [key: string]: string | string[] | undefined };

// Available tab. Header, search and view toggle come from the shared layout;
// this renders only the catalog, behind a skeleton in the selected view.
export default async function ProviderSpecsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const [tProviders, resolvedSearchParams, cookieStore] = await Promise.all([
    getTranslations("ProvidersPage"),
    searchParams,
    cookies(),
  ]);
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search.trim()
      : "";
  const tab = resolveViewMode(
    resolvedSearchParams.tab,
    cookieStore.get(MODELS_VIEW_COOKIE)?.value
  );

  const skeletonColumns = [
    { header: tProviders("table.provider"), barClassName: "h-4 w-32" },
    {
      header: tProviders("table.description"),
      cellClassName: "w-full",
      barClassName: "h-3 w-2/3",
    },
    { header: tProviders("table.models"), barClassName: "h-3 w-16" },
  ];

  return (
    <Suspense
      key={searchQuery}
      fallback={<ProvidersSkeleton viewMode={tab} columns={skeletonColumns} />}
    >
      <ProviderSpecsContent searchQuery={searchQuery} tab={tab} />
    </Suspense>
  );
}

async function ProviderSpecsContent({
  searchQuery,
  tab,
}: {
  searchQuery: string;
  tab: ModelsViewMode;
}) {
  const [t, tProviders, { canAdminister }] = await Promise.all([
    getTranslations("Common"),
    getTranslations("ProvidersPage"),
    getViewerCapabilities(),
  ]);

  let providerSpecs: ProviderSpecWithModelsResponse[] = [];
  let loadError: string | null = null;

  try {
    const providersResponse = await listProviderSpecsWithModels();
    providerSpecs = (providersResponse.data as ProviderSpecWithModelsResponse[]) || [];
    if (providersResponse.error) {
      loadError = "Failed to load provider specifications";
    }
  } catch (error) {
    console.error("Failed to load provider specifications:", error);
    loadError = "Failed to load provider specifications";
  }

  const query = searchQuery.toLowerCase();
  const visibleSpecs = query
    ? providerSpecs.filter(
        (spec) =>
          spec.name?.toLowerCase().includes(query) ||
          spec.provider_key?.toLowerCase().includes(query) ||
          spec.provider_type?.toLowerCase().includes(query)
      )
    : providerSpecs;

  if (visibleSpecs.length === 0) {
    return searchQuery && !loadError && providerSpecs.length > 0 ? (
      <EmptyState
        title={tProviders("noMatches")}
        description={tProviders("noMatchesDescription", {
          query: searchQuery,
        })}
        iconsType="llm"
        action={{ label: t("clearSearch"), href: "/models/specs" }}
      />
    ) : (
      <EmptyState
        title={loadError || tProviders("noProviders")}
        description={
          loadError
            ? "Provider specifications could not be loaded."
            : tProviders("emptyDescription")
        }
        iconsType="llm"
        action={
          canAdminister
            ? { label: tProviders("addProvider"), href: "/models" }
            : undefined
        }
      />
    );
  }

  return <ProviderSpecsView specs={visibleSpecs} viewMode={tab} />;
}
