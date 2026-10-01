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

  // Same cell styles as the Connected table and the other lists: logo on a
  // plate, medium-weight name over an 11px key, a one-line description. Type
  // and built-in status are left out: in the registry the type is the key
  // again, and every catalog entry is built in.
  const columns = [
    {
      header: tProviders("table.provider"),
      accessor: "name",
      render: (value: string, row: ProviderSpecWithModelsResponse) => (
        <div className="flex min-w-0 items-center gap-2">
          {row.icon_url && (
            <span className="avatar-plate grid h-6 w-6 flex-shrink-0 place-items-center rounded-[6px]">
              <Image
                src={row.icon_url}
                alt=""
                aria-hidden="true"
                width={20}
                height={20}
                className="h-[16px] w-[16px] object-contain"
              />
            </span>
          )}
          <div className="min-w-0">
            <div className="truncate font-medium">{value}</div>
            <div className="truncate text-[11px] text-muted-foreground">
              {row.provider_key}
            </div>
          </div>
        </div>
      ),
    },
    {
      header: tProviders("table.description"),
      accessor: "description",
      // w-full + max-w-0 lets the description take the spare width and
      // truncate inside it instead of stretching the table.
      cellClassName: "w-full max-w-0",
      render: (value: string) => (
        <div className="table-description truncate" title={value || undefined}>
          {value || "—"}
        </div>
      ),
    },
    {
      header: tProviders("table.models"),
      accessor: "models",
      render: (models: ProviderSpecWithModelsResponse["models"]) => (
        <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
          {tProviders("table.modelCount", { count: models?.length ?? 0 })}
        </span>
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
      // A catalog entry leads to connecting it. Only for those who can: a
      // member would land on a page that refuses them.
      itemLink={
        canAdminister
          ? (spec: ProviderSpecWithModelsResponse) =>
              `/models/create/${spec.id}`
          : undefined
      }
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
