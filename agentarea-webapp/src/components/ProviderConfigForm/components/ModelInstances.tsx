import { useState } from "react";
import { useTranslations } from "next-intl";
import { Brain, Eye, RefreshCw, Wrench } from "lucide-react";
import { toast } from "sonner";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  TableBody,
  TableCell,
  Table as TableComponent,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { discoverModelsAction as discoverModels } from "@/lib/server-actions";
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
  canTest?: boolean;
};

function formatCost(costPerToken: number | null | undefined): string {
  if (!costPerToken) return "—";
  const perMillion = costPerToken * 1_000_000;
  if (perMillion < 0.01) return `$${perMillion.toFixed(4)}`;
  return `$${perMillion.toFixed(2)}`;
}

function formatTokens(tokens: number | null | undefined): string {
  if (!tokens) return "—";
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}K`;
  return tokens.toLocaleString();
}

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
    if (checked) {
      const allModels = availableModels.map((model: ModelSpec) => ({
        modelSpecId: model.id,
        instanceName: `${selectedProvider?.name} ${model.display_name}`,
        description: model.description || "",
        isPublic: false,
      }));
      setSelectedModels(allModels);
    } else {
      setSelectedModels([]);
    }
  };

  const isAllSelected =
    selectedModels.length === availableModels.length &&
    availableModels.length > 0;

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

      {availableModels.length === 0 ? (
        <div className="rounded-lg bg-gray-50 p-4 text-center text-sm text-muted-foreground">
          {t("noModelsAvailableForThisProvider")}
        </div>
      ) : (
        <TableComponent>
          <TableHeader
            className="relative"
            style={{
              backgroundImage: `repeating-linear-gradient(
                -45deg,
                color-mix(in srgb, currentColor 4%, transparent),
                color-mix(in srgb, currentColor 4%, transparent) 1px,
                transparent 1px,
                transparent 10px
              )`,
            }}
          >
            <TableRow className="pointer-events-none hover:bg-transparent">
              <TableHead className="h-auto w-8 py-[4px] pl-3 pointer-events-auto">
                <Checkbox
                  checked={isAllSelected}
                  onCheckedChange={(checked) => handleSelectAllToggle(!!checked)}
                  aria-label={t("selectAllModels")}
                  id="select-all-models"
                />
              </TableHead>
              <TableHead className="h-auto py-[4px] text-[11px] font-medium uppercase text-zinc-400">
                Model
              </TableHead>
              <TableHead className="h-auto py-[4px] text-right text-[11px] font-medium uppercase text-zinc-400">
                Context
              </TableHead>
              <TableHead className="h-auto py-[4px] text-right text-[11px] font-medium uppercase text-zinc-400">
                Max Output
              </TableHead>
              <TableHead className="h-auto py-[4px] text-right text-[11px] font-medium uppercase text-zinc-400">
                Input $/1M
              </TableHead>
              <TableHead className="h-auto py-[4px] text-right text-[11px] font-medium uppercase text-zinc-400">
                Output $/1M
              </TableHead>
              <TableHead className="h-auto py-[4px] text-[11px] font-medium uppercase text-zinc-400">
                Capabilities
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {availableModels.map((model: ModelSpec) => {
              const isSelected = selectedModels.some(
                (m) => m.modelSpecId === model.id
              );
              return (
                <TableRow
                  key={model.id}
                  className="cursor-pointer border-b border-zinc-100 transition-colors duration-200 hover:bg-primary/5 dark:border-zinc-800 dark:hover:bg-primary/10"
                  onClick={() => handleModelToggle(model, !isSelected)}
                >
                  <TableCell className="w-8 py-[6px] pl-3">
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={(checked) =>
                        handleModelToggle(model, checked as boolean)
                      }
                      onClick={(e) => e.stopPropagation()}
                    />
                  </TableCell>
                  <TableCell className="py-[6px]">
                    <div className="text-sm font-medium">
                      {model.display_name}
                    </div>
                  </TableCell>
                  <TableCell className="py-[6px] text-right">
                    <span className="text-xs text-muted-foreground">
                      {formatTokens(model.context_window)}
                    </span>
                  </TableCell>
                  <TableCell className="py-[6px] text-right">
                    <span className="text-xs text-muted-foreground">
                      {formatTokens(model.max_output_tokens)}
                    </span>
                  </TableCell>
                  <TableCell className="py-[6px] text-right">
                    <span className="text-xs text-muted-foreground">
                      {formatCost(model.input_cost_per_token)}
                    </span>
                  </TableCell>
                  <TableCell className="py-[6px] text-right">
                    <span className="text-xs text-muted-foreground">
                      {formatCost(model.output_cost_per_token)}
                    </span>
                  </TableCell>
                  <TableCell className="py-[6px]">
                    <div className="flex gap-1">
                      {model.supports_function_calling && (
                        <Badge
                          variant="secondary"
                          className="gap-0.5 px-1.5 py-0 text-[10px]"
                        >
                          <Wrench className="h-2.5 w-2.5" />
                          Tools
                        </Badge>
                      )}
                      {model.supports_vision && (
                        <Badge
                          variant="secondary"
                          className="gap-0.5 px-1.5 py-0 text-[10px]"
                        >
                          <Eye className="h-2.5 w-2.5" />
                          Vision
                        </Badge>
                      )}
                      {model.supports_reasoning && (
                        <Badge
                          variant="secondary"
                          className="gap-0.5 px-1.5 py-0 text-[10px]"
                        >
                          <Brain className="h-2.5 w-2.5" />
                          Reasoning
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </TableComponent>
      )}

      {availableModels.length > 0 && (
        <div className="flex items-center">
          <Label className="note cursor-pointer text-xs font-normal">
            {t("selectedModelsCount", {
              selectedCount: selectedModels.length,
              totalCount: availableModels.length,
            })}
          </Label>
        </div>
      )}
    </div>
  );
}
