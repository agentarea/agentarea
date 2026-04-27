import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Brain, Check, Eye, RefreshCw, Search, Wrench } from "lucide-react";
import { toast } from "sonner";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  discoverModelsAction,
  discoverModelsPreviewAction,
} from "@/lib/server-actions";
import { ModelSpec } from "@/types/provider";

interface SelectedModel {
  modelSpecId: string;
  instanceName: string;
  description: string;
  isPublic: boolean;
}

type ModelInstancesProps = {
  selectedProvider: any;
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
  // In edit mode, the existing model instances are the source of truth and
  // should be visible immediately. In create mode, hide the registry-wide
  // model list until the user runs Discover so they only see models they
  // actually pulled from THIS provider/key.
  const [hasDiscovered, setHasDiscovered] = useState<boolean>(isEdit);
  const [filter, setFilter] = useState<string>("");

  const filteredModels = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return availableModels;
    return availableModels.filter((m) => {
      const haystack = `${m.display_name ?? ""} ${m.model_name ?? ""} ${m.description ?? ""}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [availableModels, filter]);

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
      if (!apiKey || !apiKey.trim()) {
        toast.error(t("enterApiKeyToDiscover"));
        return;
      }
    }
    setIsDiscovering(true);
    try {
      let totalCount = 0;
      let newCount = 0;

      if (providerConfigId) {
        const { data, error } = await discoverModelsAction(providerConfigId);
        if (error) {
          const detail = (error as any)?.detail ?? t("failedToDiscover");
          toast.error(typeof detail === "string" ? detail : t("failedToDiscover"));
          return;
        }
        const result = data as { total_discovered?: number; new_model_instances?: number };
        totalCount = result?.total_discovered ?? 0;
        newCount = result?.new_model_instances ?? 0;
      } else {
        const { data, error } = await discoverModelsPreviewAction({
          provider_key: providerKey!,
          api_key: apiKey!.trim(),
          endpoint_url: endpointUrl || null,
        });
        if (error) {
          const detail = (error as any)?.detail ?? t("failedToDiscoverCheckKey");
          toast.error(typeof detail === "string" ? detail : t("failedToDiscover"));
          return;
        }
        const result = data as { discovered?: number; new_models?: number };
        totalCount = result?.discovered ?? 0;
        newCount = result?.new_models ?? 0;
      }

      if (newCount > 0) {
        toast.success(t("discoveredCount", { totalCount, newCount }));
      } else {
        toast.success(t("discoveredCountNoNew", { totalCount }));
      }
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
      setSelectedModels([]);
    }
  }, [selectedProvider?.id, isEdit]);

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
            <RefreshCw className={`h-3 w-3 ${isDiscovering ? "animate-spin" : ""}`} />
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
          {hasDiscovered && availableModels.length > 0 && (
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
                  totalCount: availableModels.length,
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
        ) : availableModels.length === 0 ? (
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

            {availableModels.map((model: ModelSpec) => {
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

                  <div className="text-sm font-medium">{model.display_name}</div>
                  <div className="text-right text-xs text-muted-foreground">
                    {formatTokens(model.context_window)}
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {formatTokens((model as any).max_output_tokens)}
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {formatCostPerMillion((model as any).input_cost_per_token)}
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {formatCostPerMillion((model as any).output_cost_per_token)}
                  </div>

                  <div className="flex flex-wrap gap-1">
                    {(model as any).supports_function_calling && (
                      <Badge variant="secondary" className="gap-1 px-1.5 py-0 text-[10px]">
                        <Wrench className="h-2.5 w-2.5" />
                        Tools
                      </Badge>
                    )}
                    {(model as any).supports_vision && (
                      <Badge variant="secondary" className="gap-1 px-1.5 py-0 text-[10px]">
                        <Eye className="h-2.5 w-2.5" />
                        Vision
                      </Badge>
                    )}
                    {(model as any).supports_reasoning && (
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
