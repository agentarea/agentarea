import { getTranslations } from "next-intl/server";
import { listProviderConfigsWithModelInstances } from "@/lib/api";
import ProviderModelsView, {
  type ProviderModelsInitialState,
} from "./ProviderModelsView";
import { ProviderConfig, ProviderSpec } from "./types";

interface ProvidersDataProps {
  initial: ProviderModelsInitialState;
}

export default async function ProvidersData({ initial }: ProvidersDataProps) {
  const t = await getTranslations("Models");

  // Fetch provider specs and configs with model instances
  const { specs: specsResponse, configs: configsResponse } =
    await listProviderConfigsWithModelInstances();

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

  // Index specs so each config can carry its provider spec (icon, hosting, …).
  const specsMap = new Map(providerSpecs.map((spec) => [spec.id, spec]));

  // Normalize: ensure model_instances is populated (the API helper returns the
  // resolved list under `models_list`) and attach the matching spec.
  const enhancedConfigs: ProviderConfig[] = (providerConfigs as any[]).map(
    (config) => ({
      ...config,
      model_instances:
        config.model_instances ?? (config as any).models_list ?? [],
      spec: specsMap.get(config.provider_spec_id),
    })
  );

  return (
    <ProviderModelsView
      configs={enhancedConfigs}
      specs={providerSpecs}
      initial={initial}
    />
  );
}
