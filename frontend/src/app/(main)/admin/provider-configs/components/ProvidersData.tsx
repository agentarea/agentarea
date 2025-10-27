import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import {
  listProviderConfigsWithModelInstances,
  listProviderSpecsWithModels,
} from "@/lib/api";
import ProviderConfigsView from "./ProviderConfigsView";
import ProviderSpecView from "./ProviderSpecView";
import { ProviderConfig, ProviderSpec } from "./types";

interface ProvidersDataProps {
  searchQuery?: string;
  viewMode?: string;
}

export default async function ProvidersData({
  searchQuery = "",
  viewMode = "grid",
}: ProvidersDataProps) {
  const t = await getTranslations("Models");

  // Fetch provider specs and configs with model instances
  const [specsResponse, configsResponse] = await Promise.all([
    listProviderSpecsWithModels(),
    listProviderConfigsWithModelInstances(),
  ]);

  // Handle API errors
  if (specsResponse.error || configsResponse.error) {
    const specsError = specsResponse.error as any;
    const configsError = configsResponse.error as any;

    return (
      <div className="py-10 text-center">
        <p className="text-red-500">
          {t("error.loadingData")}:{" "}
          {specsError?.detail?.[0]?.msg ||
            configsError?.detail?.[0]?.msg ||
            "Unknown error occurred"}
        </p>
      </div>
    );
  }

  const providerSpecs = (specsResponse.data || []) as ProviderSpec[];
  const providerConfigs = (configsResponse.data || []) as ProviderConfig[];

  // Normalize configs to ensure model_instances is populated (fallback to models_list from API helper)
  const normalizedConfigs = (providerConfigs as any[]).map((config) => ({
    ...config,
    model_instances:
      config.model_instances ?? (config as any).models_list ?? [],
  }));

  // Create a map of provider specs for easy lookup
  const specsMap = new Map(providerSpecs.map((spec) => [spec.id, spec]));

  // Enhance configs with spec information
  const enhancedConfigs: ProviderConfig[] = normalizedConfigs.map((config: any) => ({
    ...config,
    spec: specsMap.get(config.provider_spec_id),
  }));

  // Filter provider specs based on search query
  let filteredProviderSpecs = providerSpecs;
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredProviderSpecs = providerSpecs.filter(
      (spec) =>
        spec.name?.toLowerCase().includes(query) ||
        spec.provider_key?.toLowerCase().includes(query) ||
        // spec.description?.toLowerCase().includes(query) ||
        spec.provider_type?.toLowerCase().includes(query)
    );
  }

  // Filter configs based on search query
  let filteredConfigs = enhancedConfigs;
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredConfigs = enhancedConfigs.filter(
      (config) =>
        config.name?.toLowerCase().includes(query) ||
        config.spec?.name?.toLowerCase().includes(query) ||
        config.spec?.provider_key?.toLowerCase().includes(query) ||
        config.provider_spec_name?.toLowerCase().includes(query)
    );
  }

  // Check for empty states
  const hasNoConfigs = enhancedConfigs.length === 0;
  const hasNoSpecs = providerSpecs.length === 0;
  const hasNoData = hasNoConfigs && hasNoSpecs;
  const hasNoResults =
    filteredConfigs.length === 0 &&
    filteredProviderSpecs.length === 0 &&
    !hasNoData;

  // Handle global empty states
  if (hasNoData) {
    return (
      <EmptyState
        title="No providers found"
        description="No provider configurations or specifications are available"
        iconsType="llm"
      />
    );
  }

  if (hasNoResults) {
    return (
      <EmptyState
        title="No matching providers"
        description={`No providers match your search query: "${searchQuery}"`}
        iconsType="llm"
      />
    );
  }

  // Render both views
  return (
    <div className="space-y-8">
      <div>
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          {t("providerConfigsSection")} ({filteredConfigs.length})
        </h4>
        <ProviderConfigsView
          configs={filteredConfigs}
          searchQuery={searchQuery}
          viewMode={viewMode}
          hasNoData={hasNoConfigs}
        />
      </div>

      <div>
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          {t("providerSpecsSection")} ({filteredProviderSpecs.length})
        </h4>
        <ProviderSpecView
          specs={filteredProviderSpecs}
          searchQuery={searchQuery}
          viewMode={viewMode}
          hasNoData={hasNoSpecs}
        />
      </div>
    </div>
  );
}
