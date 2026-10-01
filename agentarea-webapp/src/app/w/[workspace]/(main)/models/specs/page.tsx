import type { Metadata } from "next";
import type { ProviderSpecWithModelsResponse } from "@/api/client/types.gen";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Image from "next/image";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { listProviderSpecsWithModels } from "@/lib/api";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import { getViewerCapabilities } from "@/lib/workspace-context";
import ModelsHeaderControls from "../components/ModelsHeaderControls";
import ModelsSubheader from "../components/ModelsSubheader";
import { ProviderSpecCard } from "../components/ProviderItem";

export const metadata: Metadata = {
  title: "Providers",
};

export default async function ProviderSpecsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [t, tProviders, resolvedSearchParams, { canAdminister }, cookieStore] =
    await Promise.all([
      getTranslations("Models"),
      getTranslations("ProvidersPage"),
      searchParams,
      getViewerCapabilities(),
      cookies(),
    ]);
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search.trim()
      : "";
  // Read tab from URL or fall back to the cookie HeaderTabs writes for this path
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieStore.get("tab_models_specs")?.value || "grid";

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
          spec.name.toLowerCase().includes(query) ||
          spec.provider_key.toLowerCase().includes(query) ||
          spec.provider_type.toLowerCase().includes(query)
      )
    : providerSpecs;

  const columns = [
    {
      header: tProviders("table.provider"),
      accessor: "name",
      render: (value: unknown, spec?: ProviderSpecWithModelsResponse) => (
        <div className="flex items-center gap-2">
          {spec?.icon_url && (
            <span className="avatar-plate grid h-6 w-6 flex-shrink-0 place-items-center rounded-[6px]">
              <Image
                src={spec.icon_url}
                alt={`${spec.name} icon`}
                width={20}
                height={20}
                className="h-[16px] w-[16px] object-contain"
              />
            </span>
          )}
          <span className="truncate">{String(value)}</span>
          {spec && !spec.is_builtin && (
            <Badge variant="secondary" size="sm">
              {tProviders("table.custom")}
            </Badge>
          )}
        </div>
      ),
    },
    {
      header: tProviders("table.description"),
      accessor: "description",
      cellClassName: "max-w-[480px]",
      render: (value: unknown) => (
        <span className="line-clamp-1 text-muted-foreground">
          {(value as string | null) || tProviders("table.noDescription")}
        </span>
      ),
    },
    {
      header: tProviders("table.type"),
      accessor: "provider_type",
      cellClassName: "text-muted-foreground",
    },
    {
      header: tProviders("table.models"),
      accessor: "models",
      cellClassName: "whitespace-nowrap tabular-nums text-muted-foreground",
      render: (models: unknown) => {
        const count = (models as unknown[]).length;
        return count ? tProviders("table.modelsCount", { count }) : "—";
      },
    },
  ];

  const content = loadError || !providerSpecs.length ? (
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
          ? { label: tProviders("addProvider"), href: "/models/create" }
          : undefined
      }
    />
  ) : !visibleSpecs.length ? (
    <EmptyState
      title="No matching providers"
      description={`No providers match your search query: "${searchQuery}"`}
      iconsType="llm"
      action={{ label: "Clear search", href: "/models/specs" }}
    />
  ) : tab === "table" ? (
    <Table
      data={visibleSpecs}
      columns={columns}
      rowHref={(spec) => `/models/create/${spec.id}`}
    />
  ) : (
    <div className={CARD_GRID_DENSE}>
      {visibleSpecs.map((spec) => (
        <ProviderSpecCard
          key={spec.id}
          spec={spec}
          customLabel={tProviders("table.custom")}
          modelCountLabel={
            spec.models.length
              ? tProviders("table.modelsCount", { count: spec.models.length })
              : null
          }
          noDescriptionLabel={tProviders("table.noDescription")}
        />
      ))}
    </div>
  );

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title"), href: "/models" }],
        description: t("description"),
        controls: <ModelsHeaderControls canAdminister={canAdminister} />,
      }}
      subheader={<ModelsSubheader path="/models/specs" currentTab={tab} />}
    >
      {content}
    </ContentBlock>
  );
}
