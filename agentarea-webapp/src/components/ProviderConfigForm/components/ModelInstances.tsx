import { useState } from "react";
import { useTranslations } from "next-intl";
import { Brain, Check, Eye, RefreshCw, Wrench } from "lucide-react";
import { toast } from "sonner";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

// Plain checkbox indicator — zero Radix, zero hooks
function CheckIndicator({ checked }: { checked: boolean }) {
  return (
    <div
      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border shadow-sm ${
        checked
          ? "border-primary bg-primary text-primary-foreground"
          : "border-primary"
      }`}
    >
      {checked && <Check className="h-3 w-3" />}
    </div>
  );
}

export default function ModelInstances({
  selectedProvider,
  availableModels,
  selectedModels,
  setSelectedModels,
  isEdit = false,
  providerConfigId,
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

  const isAllSelected =
    selectedModels.length === availableModels.length &&
    availableModels.length > 0;

  const handleSelectAll = () => {
    if (isAllSelected) {
      setSelectedModels([]);
    } else {
      setSelectedModels(
        availableModels.map((model) => ({
          modelSpecId: model.id,
          instanceName: `${selectedProvider?.name} ${model.display_name}`,
          description: model.description || "",
          isPublic: false,
        }))
      );
    }
  };

  const handleRowClick = (model: ModelSpec) => {
    const isSelected = selectedModels.some((m) => m.modelSpecId === model.id);
    if (isSelected) {
      setSelectedModels(
        selectedModels.filter((m) => m.modelSpecId !== model.id)
      );
    } else {
      setSelectedModels([
        ...selectedModels,
        {
          modelSpecId: model.id,
          instanceName: `${selectedProvider?.name} ${model.display_name}`,
          description: model.description || "",
          isPublic: false,
        },
      ]);
    }
  };

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
        <div className="overflow-hidden rounded-md border">
          {/* Header */}
          <div
            className="grid grid-cols-[32px_1fr_80px_80px_80px_80px_140px] items-center gap-2 px-3 py-1.5 text-[11px] font-medium uppercase text-zinc-400"
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
            <div
              className="flex cursor-pointer items-center justify-center"
              onClick={handleSelectAll}
            >
              <CheckIndicator checked={isAllSelected} />
            </div>
            <div>Model</div>
            <div className="text-right">Context</div>
            <div className="text-right">Max Output</div>
            <div className="text-right">Input $/1M</div>
            <div className="text-right">Output $/1M</div>
            <div>Capabilities</div>
          </div>

          {/* Rows */}
          {availableModels.map((model) => {
            const isSelected = selectedModels.some(
              (m) => m.modelSpecId === model.id
            );
            return (
              <div
                key={model.id}
                className="grid cursor-pointer grid-cols-[32px_1fr_80px_80px_80px_80px_140px] items-center gap-2 border-t border-zinc-100 px-3 py-1.5 transition-colors duration-200 hover:bg-primary/5 dark:border-zinc-800 dark:hover:bg-primary/10"
                onClick={() => handleRowClick(model)}
              >
                <div className="flex items-center justify-center">
                  <CheckIndicator checked={isSelected} />
                </div>
                <div className="text-sm font-medium">
                  {model.display_name}
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  {formatTokens(model.context_window)}
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  {formatTokens(model.max_output_tokens)}
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  {formatCost(model.input_cost_per_token)}
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  {formatCost(model.output_cost_per_token)}
                </div>
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
              </div>
            );
          })}
        </div>
      )}

      {availableModels.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t("selectedModelsCount", {
            selectedCount: selectedModels.length,
            totalCount: availableModels.length,
          })}
        </p>
      )}
    </div>
  );
}
