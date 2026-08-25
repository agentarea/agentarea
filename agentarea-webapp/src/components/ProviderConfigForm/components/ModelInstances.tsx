import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Brain, Check, Eye, RefreshCw, Wrench } from "lucide-react";
import { toast } from "sonner";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Badge } from "@/components/ui/badge";
import { ProviderIcon } from "@/components/ui/provider-icon";
import { Button } from "@/components/ui/button";
import {
  discoverModelsAction,
  discoverModelsPreviewAction,
} from "@/lib/server-actions";
import { ModelSpec, ProviderSpec } from "@/types/provider";
import { filterModelsByDiscovery } from "./modelDiscovery";

interface SelectedModel {
  modelSpecId: string;
  instanceName: string;
  description: string;
  isPublic: boolean;
}

type ModelInstancesProps = {
  selectedProvider: ProviderSpec;
  availableModels: ModelSpec[];
  selectedModels: SelectedModel[];
  setSelectedModels: (models: SelectedModel[]) => void;
  isEdit?: boolean;
  providerConfigId?: string;
  apiKey?: string;
  endpointUrl?: string | null;
  onModelsDiscovered?: () => Promise<void> | void;
};

export default function ModelInstances({
  selectedProvider,
  availableModels,
  selectedModels,
  setSelectedModels,
  isEdit = false,
  providerConfigId,
  apiKey,
  endpointUrl,
  onModelsDiscovered,
}: ModelInstancesProps) {
  const t = useTranslations("ProviderConfigForm");
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoveredModelNames, setDiscoveredModelNames] =
    useState<ReadonlySet<string> | null>(null);
  // In edit mode, the existing model instances are the source of truth and
  // should be visible immediately. In create mode, hide the registry-wide
  // model list until the user runs Discover so they only see models they
  // actually pulled from THIS provider/key.
  const [hasDiscovered, setHasDiscovered] = useState<boolean>(isEdit);
  const [filter] = useState<string>("");

  const visibleModels = useMemo(
    () => filterModelsByDiscovery(availableModels, discoveredModelNames),
    [availableModels, discoveredModelNames]
  );

  const filteredModels = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return visibleModels;
    return visibleModels.filter((m) => {
      const haystack =
        `${m.display_name ?? ""} ${m.model_name ?? ""} ${m.description ?? ""}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [visibleModels, filter]);

  const formatTokens = (tokens?: number | null) => {
    if (tokens == null) return "-";
    return tokens.toLocaleString();
  };

  const formatCostPerMillion = (costPerToken?: number | null) => {
    if (costPerToken == null) return "-";
    return `$${(costPerToken * 1_000_000).toFixed(2)}`;
  };

  const providerKey: string | undefined = selectedProvider?.provider_key;

  const handleDiscoverModels = async () => {
    if (!providerConfigId) {
      if (!providerKey) {
        toast.error(t("selectProviderFirst"));
        return;
      }
      // Keyless proxies (custom endpoint, no auth) can still be discovered.
      if ((!apiKey || !apiKey.trim()) && (!endpointUrl || !endpointUrl.trim())) {
        toast.error(t("enterApiKeyToDiscover"));
        return;
      }
    }
    setIsDiscovering(true);
    try {
      let totalCount = 0;
      let newCount = 0;
      let discoveredNames: string[] = [];

      if (providerConfigId) {
        const { data, error } = await discoverModelsAction(providerConfigId);
        if (error) {
          const detail = (error as { detail?: unknown })?.detail;
          toast.error(typeof detail === "string" ? detail : t("failedToDiscover"));
          return;
        }
        totalCount = data?.discovered ?? 0;
        newCount = data?.new_models ?? 0;
        discoveredNames = data?.models.map((model) => model.model_name) ?? [];
      } else {
        const { data, error } = await discoverModelsPreviewAction({
          provider_key: providerKey ?? "",
          api_key: apiKey?.trim() || "",
          endpoint_url: endpointUrl || null,
        });
        if (error) {
          // Surface the real backend error. Only fall back to a NEUTRAL generic
          // message — never blame the API key for non-auth failures (e.g. a 500
          // would otherwise be reported as "Check API key", which is misleading).
          const e = error as { detail?: unknown; message?: unknown };
          const d = e?.detail;
          const msg =
            typeof d === "string" && d
              ? d
              : Array.isArray(d) && typeof d[0]?.msg === "string"
                ? d[0].msg
                : typeof e?.message === "string"
                  ? e.message
                  : t("failedToDiscover");
          toast.error(msg);
          return;
        }
        totalCount = data?.discovered ?? 0;
        newCount = data?.new_models ?? 0;
        discoveredNames = data?.models.map((model) => model.model_name) ?? [];
      }

      if (newCount > 0) {
        toast.success(t("discoveredCount", { totalCount, newCount }));
      } else {
        toast.success(t("discoveredCountNoNew", { totalCount }));
      }
      setDiscoveredModelNames(new Set(discoveredNames));
      setHasDiscovered(true);
      await onModelsDiscovered?.();
    } catch (err) {
      console.error("discover models failed", err);
      toast.error(t("failedToDiscover"));
    } finally {
      setIsDiscovering(false);
    }
  };

  // Reset discovery state when the provider changes — the previously
  // discovered list belonged to a different provider and must not bleed in.
  useEffect(() => {
    if (!isEdit) {
      setHasDiscovered(false);
      setDiscoveredModelNames(null);
      setSelectedModels([]);
    }
  }, [selectedProvider?.id, isEdit, setSelectedModels]);

  // Note: we deliberately do NOT auto-select discovered models. Providers like
  // OpenRouter return hundreds of models and selecting them all would create
  // hundreds of ModelInstance rows on submit. The user picks what they need.

  const handleModelToggle = (modelSpec: ModelSpec, checked: boolean) => {
    if (checked) {
      const newModel: SelectedModel = {
        modelSpecId: modelSpec.id,
        instanceName: `${selectedProvider?.name} ${modelSpec.display_name}`,
        description: modelSpec.description || "",
        isPublic: false,
      };
      setSelectedModels([...selectedModels, newModel]);
    } else {
      setSelectedModels(
        selectedModels.filter(
          (m: SelectedModel) => m.modelSpecId !== modelSpec.id
        )
      );
    }
  };

  const toRow = (model: ModelSpec): SelectedModel => ({
    modelSpecId: model.id,
    instanceName: `${selectedProvider?.name} ${model.display_name}`,
    description: model.description || "",
    isPublic: false,
  });

  // Select-all toggles only what's currently visible (after filter), so users
  // can narrow the list and bulk-select a subset rather than all 300+ rows.
  const handleSelectAllToggle = (checked: boolean) => {
    const filteredIds = new Set(filteredModels.map((m) => m.id));
    const remaining = selectedModels.filter((m) => !filteredIds.has(m.modelSpecId));
    if (checked || isIndeterminate) {
      setSelectedModels([...remaining, ...filteredModels.map(toRow)]);
    } else {
      setSelectedModels(remaining);
    }
  };

  const filteredSelectedCount = selectedModels.filter((m) =>
    filteredModels.some((fm) => fm.id === m.modelSpecId)
  ).length;
  const isAllSelected =
    filteredSelectedCount === filteredModels.length && filteredModels.length > 0;
  const isIndeterminate =
    filteredSelectedCount > 0 && filteredSelectedCount < filteredModels.length;

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <FormLabel icon={Brain}>{t("modelInstances")}</FormLabel>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleDiscoverModels}
            disabled={isDiscovering}
            className="h-7 gap-1.5 text-xs"
            title={
              providerConfigId
                ? t("discoverModelsTooltip")
                : t("testAndDiscoverTooltip")
            }
          >
            <RefreshCw className={isDiscovering ? "animate-spin" : ""} />
            {isDiscovering
              ? t("discovering")
              : providerConfigId
                ? t("discoverModels")
                : t("testAndDiscover")}
          </Button>
        </div>
        <p className="note">
          {t("selectModelsToCreateInstances", {
            providerName: selectedProvider.name,
          })}
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          {hasDiscovered && visibleModels.length > 0 && (
            <div className="mx-3 flex items-center space-x-2">
              <button
                type="button"
                aria-label={t("selectAllModels")}
                className="flex h-4 w-4 items-center justify-center rounded-sm border border-primary shadow-sm"
                onClick={() => handleSelectAllToggle(!isAllSelected || isIndeterminate)}
              >
                {(isAllSelected || isIndeterminate) && <Check className="h-3 w-3" />}
              </button>
              <span className="note cursor-pointer text-xs font-normal">
                {t("selectedModelsCount", {
                  selectedCount: selectedModels.length,
                  totalCount: visibleModels.length,
                })}
              </span>
            </div>
          )}
        </div>

        {!hasDiscovered ? (
          <div className="rounded-lg border border-dashed bg-muted/30 p-6 text-center">
            <Brain className="mx-auto mb-2 h-6 w-6 text-muted-foreground/60" />
            <p className="text-sm font-medium">{t("noModelsLoaded")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("noModelsLoadedHint", { action: t("testAndDiscover") })}
            </p>
          </div>
        ) : visibleModels.length === 0 ? (
          <div className="rounded-lg bg-gray-50 p-4 text-center text-sm text-muted-foreground">
            {t("noModelsAvailableForThisProvider")}
          </div>
        ) : (
          <div className="overflow-hidden rounded-md border">
            <div className="grid grid-cols-[32px_1fr_90px_90px_100px_100px_180px] items-center gap-2 border-b bg-muted/40 px-3 py-2 text-[11px] font-medium uppercase text-muted-foreground">
              <div className="flex items-center justify-center" />
              <div>Model</div>
              <div className="text-right">Context</div>
              <div className="text-right">Max Out</div>
              <div className="text-right">Input $/1M</div>
              <div className="text-right">Output $/1M</div>
              <div>Capabilities</div>
            </div>

            {visibleModels.map((model: ModelSpec) => {
              const isSelected = selectedModels.some((m) => m.modelSpecId === model.id);
              return (
                <div
                  key={model.id}
                  className="grid cursor-pointer grid-cols-[32px_1fr_90px_90px_100px_100px_180px] items-center gap-2 border-b px-3 py-2 hover:bg-primary/5"
                  onClick={() => handleModelToggle(model, !isSelected)}
                >
                  <div className="flex items-center justify-center">
                    <div className="flex h-4 w-4 items-center justify-center rounded-sm border border-primary shadow-sm">
                      {isSelected && <Check className="h-3 w-3" />}
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 text-sm font-medium">
                    {selectedProvider?.icon_url && (
                      <ProviderIcon
                        iconUrl={selectedProvider.icon_url}
                        name={selectedProvider?.name || model.display_name}
                        size="sm"
                      />
                    )}
                    <span className="truncate">{model.display_name}</span>
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {formatTokens(model.context_window)}
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {formatTokens(model.max_output_tokens)}
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {formatCostPerMillion(model.input_cost_per_token)}
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {formatCostPerMillion(model.output_cost_per_token)}
                  </div>

                  <div className="flex flex-wrap gap-1">
                    {model.supports_function_calling && (
                      <Badge variant="secondary" className="gap-1 px-1.5 py-0 text-[10px]">
                        <Wrench className="h-2.5 w-2.5" />
                        Tools
                      </Badge>
                    )}
                    {model.supports_vision && (
                      <Badge variant="secondary" className="gap-1 px-1.5 py-0 text-[10px]">
                        <Eye className="h-2.5 w-2.5" />
                        Vision
                      </Badge>
                    )}
                    {model.supports_reasoning && (
                      <Badge variant="secondary" className="gap-1 px-1.5 py-0 text-[10px]">
                        <Brain className="h-2.5 w-2.5" />
                        Reasoning
                      </Badge>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
