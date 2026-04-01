import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Brain, Check, Eye, RefreshCw, Wrench } from "lucide-react";
import { toast } from "sonner";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { discoverModelsAction } from "@/lib/server-actions";
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
  onModelsDiscovered?: () => Promise<void> | void;
};

export default function ModelInstances({
  selectedProvider,
  availableModels,
  selectedModels,
  setSelectedModels,
  isEdit = false,
  providerConfigId,
  onModelsDiscovered,
}: ModelInstancesProps) {
  const t = useTranslations("ProviderConfigForm");
  const [isDiscovering, setIsDiscovering] = useState(false);

  const formatTokens = (tokens?: number | null) => {
    if (tokens == null) return "-";
    return tokens.toLocaleString();
  };

  const formatCostPerMillion = (costPerToken?: number | null) => {
    if (costPerToken == null) return "-";
    return `$${(costPerToken * 1_000_000).toFixed(2)}`;
  };

  const handleDiscoverModels = async () => {
    if (!providerConfigId) return;
    setIsDiscovering(true);
    try {
      const { data, error } = await discoverModelsAction(providerConfigId);
      if (error) {
        toast.error("Failed to discover models");
        return;
      }
      const result = data as { total_discovered?: number; new_model_instances?: number };
      const totalCount = result?.total_discovered ?? 0;
      const newCount = result?.new_model_instances ?? 0;
      if (newCount > 0) {
        toast.success(`Discovered ${totalCount} models (${newCount} new)`);
      } else {
        toast.success(`Discovered ${totalCount} models (no new models)`);
      }
      await onModelsDiscovered?.();
    } catch {
      toast.error("Failed to discover models");
    } finally {
      setIsDiscovering(false);
    }
  };

  // Auto-select all models when component loads or availableModels changes (only for new configs)
  useEffect(() => {
    if (selectedProvider && availableModels.length > 0 && !isEdit) {
      const allModels = availableModels.map((model: ModelSpec) => ({
        modelSpecId: model.id,
        instanceName: `${selectedProvider?.name} ${model.display_name}`,
        description: model.description || "",
        isPublic: false,
      }));
      setSelectedModels(allModels);
    }
  }, [selectedProvider, availableModels, isEdit]);

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

  const handleSelectAllToggle = (checked: boolean) => {
    // If indeterminate state, always select all
    if (isIndeterminate) {
      const allModels = availableModels.map((model: ModelSpec) => ({
        modelSpecId: model.id,
        instanceName: `${selectedProvider?.name} ${model.display_name}`,
        description: model.description || "",
        isPublic: false,
      }));
      setSelectedModels(allModels);
    } else if (checked) {
      // Select all models
      const allModels = availableModels.map((model: ModelSpec) => ({
        modelSpecId: model.id,
        instanceName: `${selectedProvider?.name} ${model.display_name}`,
        description: model.description || "",
        isPublic: false,
      }));
      setSelectedModels(allModels);
    } else {
      // Clear all models
      setSelectedModels([]);
    }
  };

  const isAllSelected =
    selectedModels.length === availableModels.length &&
    availableModels.length > 0;
  const isIndeterminate =
    selectedModels.length > 0 && selectedModels.length < availableModels.length;

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <FormLabel icon={Brain}>{t("modelInstances")}</FormLabel>
          {providerConfigId && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleDiscoverModels}
              disabled={isDiscovering}
              className="h-7 gap-1.5 text-xs"
            >
              <RefreshCw className={`h-3 w-3 ${isDiscovering ? "animate-spin" : ""}`} />
              {isDiscovering ? "Discovering..." : "Discover Models"}
            </Button>
          )}
        </div>
        <p className="note">
          {t("selectModelsToCreateInstances", {
            providerName: selectedProvider.name,
          })}
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          {availableModels.length > 0 && (
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

        {availableModels.length === 0 ? (
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
