"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import ModelBadge from "@/components/ui/model-badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import {
  listModelInstancesAction,
  sendTaskCommandAction,
} from "@/lib/server-actions";
import { ModelInstance } from "@/types/provider";

interface ModelPickerProps {
  agentId: string;
  taskId: string;
  currentModelId?: string;
  isActive: boolean;
}

export default function ModelPicker({
  agentId,
  taskId,
  currentModelId,
  isActive,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [models, setModels] = useState<ModelInstance[]>([]);
  const [error, setError] = useState<string | null>(null);
  const t = useTranslations("TaskInfoPanel");
  const tCommon = useTranslations("Common");

  if (!isActive) {
    return null;
  }

  const handleOpen = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await listModelInstancesAction({
        is_active: true,
        kind: "chat",
      });
      if (result.error || !Array.isArray(result.data)) {
        setError(apiErrorMessage(result, t("modelsLoadFailed")));
        return;
      }
      setModels(result.data);
      setOpen(true);
    } catch (err) {
      console.error("Failed to load models", err);
      setError(`${t("modelsLoadFailed")}: ${formatApiError(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = async (modelInstanceId: string) => {
    if (modelInstanceId === currentModelId) {
      setOpen(false);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await sendTaskCommandAction(agentId, taskId, {
        command: "change_model",
        model_instance_id: modelInstanceId,
      });
      if (result.error) {
        setError(apiErrorMessage(result, t("modelChangeFailed")));
        return;
      }
      setOpen(false);
    } catch (err) {
      console.error("Failed to change task model", err);
      setError(`${t("modelChangeFailed")}: ${formatApiError(err)}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-1 space-y-1">
      <div className="flex items-center gap-2">
        {open ? (
          <div className="flex items-center gap-2 w-full">
            <Select onValueChange={handleSelect} defaultValue={currentModelId}>
              <SelectTrigger className="h-7 text-xs">
                <SelectValue placeholder={t("selectModel")} />
              </SelectTrigger>
              <SelectContent>
                {models.map((model) => (
                  <SelectItem key={model.id} value={model.id} className="text-xs">
                    <ModelBadge
                      size="sm"
                      className="bg-transparent px-0 py-0"
                      providerName={model.provider_name ?? undefined}
                      iconUrl={model.provider_icon_url ?? undefined}
                      modelDisplayName={
                        model.model_display_name || model.name || model.id
                      }
                    />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {submitting && (
              <Loader2 className="h-3 w-3 animate-spin text-muted-foreground shrink-0" />
            )}
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => setOpen(false)}
              disabled={submitting}
            >
              {tCommon("cancel")}
            </Button>
          </div>
        ) : (
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={handleOpen}
            disabled={loading}
          >
            {loading ? (
              <Loader2 className="animate-spin" />
            ) : (
              t("changeModel")
            )}
          </Button>
        )}
      </div>
      {error && <FormError>{error}</FormError>}
    </div>
  );
}
