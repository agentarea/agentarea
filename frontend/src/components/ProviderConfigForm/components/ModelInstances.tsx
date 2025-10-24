import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Brain } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
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
        <FormLabel icon={Brain}>{t("modelInstances")}</FormLabel>
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
