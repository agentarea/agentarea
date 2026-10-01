import type { Metadata } from "next";
import type { ProviderSpecWithModelsResponse } from "@/api/client/types.gen";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import Image from "next/image";
import { listProviderSpecsWithModels } from "@/lib/api";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { ProviderSpecsSkeleton } from "../../components/ProvidersSkeleton";
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
    { header: tProviders("table.description"), barClassName: "h-3 w-48" },
    { header: tProviders("table.type"), barClassName: "h-5 w-20 rounded-full" },
    { header: tProviders("table.models"), barClassName: "h-3 w-16" },
    { header: tProviders("table.status"), barClassName: "h-5 w-16 rounded-full" },
  ];

  return (
    <Suspense
      key={searchQuery}
      fallback={<ProviderSpecsSkeleton viewMode={tab} columns={skeletonColumns} />}
    >
      <ProviderSpecsContent
        searchParams={resolvedSearchParams}
        searchQuery={searchQuery}
        tab={tab}
      />
    </Suspense>
  );
}

async function ProviderSpecsContent({
  searchParams,
  searchQuery,
  tab,
}: {
  searchParams: SearchParams;
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

  const columns = [
    {
      header: tProviders("table.provider"),
      accessor: "name",
      render: (value: string, row: ProviderSpecWithModelsResponse) => (
        <div className="flex items-center gap-3">
          {row.icon_url && (
            <Image
              src={row.icon_url}
              alt={`${value} icon`}
              width={24}
              height={24}
              className="h-6 w-6 rounded"
            />
          )}
          <div>
            <div className="text-[14px] font-semibold md:text-[16px]">
              {value}
            </div>
            <div className="text-xs text-muted-foreground">
              {row.provider_key}
            </div>
          </div>
        </div>
      ),
    },
    {
      header: tProviders("table.description"),
      accessor: "description",
      cellClassName: "text-[12px] md:text-[14px]",
      render: (value: string) => (
        <div className="line-clamp-3 md:line-clamp-none">
          {value || tProviders("table.noDescription")}
        </div>
      ),
    },
    {
      header: tProviders("table.type"),
      accessor: "provider_type",
      render: (value: string) => (
        <div className="rounded-full bg-blue-100 px-2 py-1 text-xs text-blue-800">
          {value}
        </div>
      ),
    },
    {
      header: tProviders("table.models"),
      accessor: "models",
      render: (models: ProviderSpecWithModelsResponse["models"]) => (
        <div className="text-xs text-muted-foreground">
          {models?.length || 0} {tProviders("table.modelsCount")}
        </div>
      ),
    },
    {
      header: tProviders("table.status"),
      accessor: "is_builtin",
      render: (value: boolean) => (
        <div
          className={`rounded-full px-2 py-1 text-xs ${
            value ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-800"
          }`}
        >
          {value ? tProviders("table.builtIn") : tProviders("table.custom")}
        </div>
      ),
    },
  ];

  return (
    <GridAndTableViews
      searchParams={{ ...searchParams, tab }}
      toolbar={false}
      data={visibleSpecs}
      columns={columns}
      emptyState={
        searchQuery && !loadError && providerSpecs.length > 0 ? (
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
        )
      }
      routeChange="/models/specs"
      cardContent={(item: ProviderSpecWithModelsResponse) => (
        <div className="flex flex-col gap-2">
          <div className="mb-2 flex items-center gap-3">
            {item.icon_url && (
              <Image
                src={item.icon_url}
                alt={`${item.name} icon`}
                width={32}
                height={32}
                className="h-8 w-8 rounded"
              />
            )}
            <div>
              <div className="text-[16px] font-[500]">
                {item.name}
              </div>
              <div className="text-xs text-muted-foreground">
                {item.provider_key}
              </div>
            </div>
          </div>
          <div className="line-clamp-2 text-[14px] opacity-50">
            {item.description || tProviders("table.noDescription")}
          </div>
          <div className="flex gap-2 text-xs text-muted-foreground">
            <span>
              {tProviders("table.type")}: {item.provider_type}
            </span>
            <span>•</span>
            <span>
              {tProviders("table.models")}: {item.models?.length || 0}
            </span>
          </div>
          <div className="flex gap-2">
            <div
              className={`rounded-full px-2 py-1 text-xs ${
                item.is_builtin
                  ? "bg-green-100 text-green-800"
                  : "bg-gray-100 text-gray-800"
              }`}
            >
              {item.is_builtin
                ? tProviders("table.builtIn")
                : tProviders("table.custom")}
            </div>
          </div>
        </div>
      )}
    />
  );
}
