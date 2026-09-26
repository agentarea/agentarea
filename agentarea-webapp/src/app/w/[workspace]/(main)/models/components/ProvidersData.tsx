import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { listProviderConfigsWithModelInstances } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getViewerCapabilities } from "@/lib/workspace-context";
import PlatformProviderConfigsView from "./PlatformProviderConfigsView";
import ProviderConfigsView from "./ProviderConfigsView";
import { ProviderConfig, ProviderSpec } from "./types";

function matchesQuery(config: ProviderConfig, query: string) {
  return (
    config.name?.toLowerCase().includes(query) ||
    config.spec?.name?.toLowerCase().includes(query) ||
    config.spec?.provider_key?.toLowerCase().includes(query) ||
    config.provider_spec_name?.toLowerCase().includes(query)
  );
}

interface ProvidersDataProps {
  searchQuery?: string;
  viewMode?: string;
}

export default async function ProvidersData({
  searchQuery = "",
  viewMode = "grid",
}: ProvidersDataProps) {
  const [
    t,
    tAdmin,
    { canAdminister },
    { specs: specsResponse, configs: configsResponse },
  ] = await Promise.all([
    getTranslations("Models"),
    getTranslations("AdminOnly"),
    getViewerCapabilities(),
    listProviderConfigsWithModelInstances(),
  ]);

  // Handle API errors
  if (specsResponse.error || configsResponse.error) {
    const failed = configsResponse.error ? configsResponse : specsResponse;

    return (
      <div className="py-10 text-center">
        <p className="text-red-500">
          {apiErrorMessage(failed, t("error.loadingData"))}
        </p>
      </div>
    );
  }

  const providerSpecs = (specsResponse.data || []) as ProviderSpec[];
  const providerConfigs = (configsResponse.data || []) as ProviderConfig[];

  // Normalize configs to ensure model_instances is populated (fallback to models_list from API helper)
  type RawConfig = ProviderConfig & { models_list?: ProviderConfig["model_instances"] };
  const normalizedConfigs = (providerConfigs as RawConfig[]).map((config) => ({
    ...config,
    model_instances:
      config.model_instances ?? config.models_list ?? [],
  }));

  // Create a map of provider specs for easy lookup
  const specsMap = new Map(providerSpecs.map((spec) => [spec.id, spec]));

  // Enhance configs with spec information
  const enhancedConfigs: ProviderConfig[] = normalizedConfigs.map((config) => ({
    ...config,
    spec: specsMap.get(config.provider_spec_id),
  }));

  // Platform-supplied configs are read-only and get their own section, above
  // the customer's own -- see PlatformProviderConfigsView.
  const platformConfigs = enhancedConfigs.filter(
    (config) => config.managed_by === "platform"
  );
  const ownConfigs = enhancedConfigs.filter(
    (config) => config.managed_by !== "platform"
  );

  // A spec already covered by a platform config isn't something the customer
  // can add themselves, so it's dropped from "available providers" entirely
  // rather than showing up as both configured and addable.
  const platformSpecIds = new Set(
    platformConfigs.map((config) => config.provider_spec_id)
  );
  const availableProviderSpecs = providerSpecs.filter(
    (spec) => !platformSpecIds.has(spec.id)
  );

  // Filter provider specs based on search query
  let filteredProviderSpecs = availableProviderSpecs;
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredProviderSpecs = availableProviderSpecs.filter(
      (spec) =>
        spec.name?.toLowerCase().includes(query) ||
        spec.provider_key?.toLowerCase().includes(query) ||
        // spec.description?.toLowerCase().includes(query) ||
        spec.provider_type?.toLowerCase().includes(query)
    );
  }

  // Filter configs based on search query
  let filteredPlatformConfigs = platformConfigs;
  let filteredOwnConfigs = ownConfigs;
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredPlatformConfigs = platformConfigs.filter((config) =>
      matchesQuery(config, query)
    );
    filteredOwnConfigs = ownConfigs.filter((config) =>
      matchesQuery(config, query)
    );
  }

  // Check for empty states. hasNoConfigs covers platform + own, so a
  // workspace with only platform-supplied providers is never told it has
  // none; hasNoOwnConfigs is scoped to the customer's own section only.
  const hasNoConfigs = enhancedConfigs.length === 0;
  const hasNoOwnConfigs = ownConfigs.length === 0;
  const hasNoSpecs = availableProviderSpecs.length === 0;
  const hasNoData = hasNoConfigs && hasNoSpecs;
  const hasNoResults =
    filteredPlatformConfigs.length === 0 &&
    filteredOwnConfigs.length === 0 &&
    filteredProviderSpecs.length === 0 &&
    !hasNoData;

  // Handle global empty states
  if (hasNoData) {
    return (
      <EmptyState
        title="No models connected"
        description="Agents cannot run without a model. Connect a provider with your own key — OpenAI, Anthropic, or any compatible endpoint."
        hints={[
          canAdminister
            ? {
                text: "Add a provider and paste its API key",
                href: "/models/create",
              }
            : { text: tAdmin("hints.manageProvider") },
          { text: "Choose which of its models this workspace may use" },
          { text: "Agents then pick a model from what you allowed" },
        ]}
        iconsType="llm"
        action={
          canAdminister
            ? { label: "Add provider", href: "/models/create" }
            : undefined
        }
      />
    );
  }

  if (hasNoResults) {
    return (
      <EmptyState
        title="No matching providers"
        description={`No providers match your search query: "${searchQuery}"`}
        iconsType="llm"
        action={{ label: "Clear search", href: "/models" }}
      />
    );
  }

  // Platform-supplied configurations come first: they are the ones already
  // working, with nothing for the customer to do. The section is absent
  // entirely in a deployment that supplies none, which is most of them.
  return (
    <div className="space-y-8">
      {platformConfigs.length > 0 &&
        (filteredPlatformConfigs.length > 0 || !searchQuery.trim()) && (
          <div>
            <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
              {t("platformProviderConfigsSection")} (
              {filteredPlatformConfigs.length})
            </h4>
            <PlatformProviderConfigsView
              configs={filteredPlatformConfigs}
              viewMode={viewMode}
            />
          </div>
        )}

      {(filteredOwnConfigs.length > 0 || !searchQuery.trim()) && (
        <div>
          <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
            {t("providerConfigsSection")} ({filteredOwnConfigs.length})
          </h4>
          <ProviderConfigsView
            configs={filteredOwnConfigs}
            searchQuery={searchQuery}
            viewMode={viewMode}
            hasNoData={hasNoOwnConfigs}
          />
        </div>
      )}

      {/* Providers you could add, but haven't, are a catalog — they live on the
          "Available" tab. Listing them here meant this page answered "what
          could exist" at the same volume as "what my agents can actually
          use", and burying them in a footnote was no better. */}
    </div>
  );
}
