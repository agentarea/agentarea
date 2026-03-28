import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Brain, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { discoverModelsAction as discoverModels } from "@/lib/server-actions";
import { ModelSpec } from "@/types/provider";
import { ModelItemControl } from "./ModelItemControl";

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
  canTest?: boolean;
};

export default function ModelInstances({
  selectedProvider,
  availableModels,
  selectedModels,
  setSelectedModels,
  isEdit = false,
  providerConfigId,
  canTest = false,
}: ModelInstancesProps) {
  const t = useTranslations("ProviderConfigForm");
  const [isSyncing, setIsSyncing] = useState(false);

  const handleSyncModels = async () => {
    if (!providerConfigId) return;
    setIsSyncing(true);
    try {
      const { data, error } = await discoverModels(providerConfigId);
      if (error) {
        const message = (error as any)?.detail || "Failed to discover models";
        toast.error(message);
        return;
      }
      const result = data as any;
      if (result?.new_models > 0) {
        toast.success(
          `Discovered ${result.discovered} models (${result.new_models} new). Reload the page to see them.`
        );
      } else {
        toast.info(`${result?.discovered || 0} models found, all up to date`);
      }
    } catch {
      toast.error("Failed to sync models");
    } finally {
      setIsSyncing(false);
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
              size="xs"
              variant="outline"
              onClick={handleSyncModels}
              disabled={isSyncing}
            >
              <RefreshCw
                className={`mr-1.5 h-3 w-3 ${isSyncing ? "animate-spin" : ""}`}
              />
              {isSyncing ? "Syncing..." : "Sync Models"}
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
              <Checkbox
                checked={isAllSelected}
                indeterminate={isIndeterminate}
                onCheckedChange={handleSelectAllToggle}
                aria-label={t("selectAllModels")}
                id="select-all-models"
              />
              <Label
                className="note cursor-pointer text-xs font-normal"
                htmlFor="select-all-models"
              >
                {t("selectedModelsCount", {
                  selectedCount: selectedModels.length,
                  totalCount: availableModels.length,
                })}
              </Label>
            </div>
          )}
        </div>

        {availableModels.length === 0 ? (
          <div className="rounded-lg bg-gray-50 p-4 text-center text-sm text-muted-foreground">
            {t("noModelsAvailableForThisProvider")}
          </div>
        ) : (
          <div className="space-y-3 overflow-y-auto">
            {availableModels.map((model: ModelSpec, key) => {
              return (
                <ModelItemControl
                  key={model.id}
                  model={model}
                  isSelected={selectedModels.some(
                    (m) => m.modelSpecId === model.id
                  )}
                  onSelect={(checked) =>
                    handleModelToggle(model, checked as boolean)
                  }
                  providerConfigId={providerConfigId}
                  canTest={canTest}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
