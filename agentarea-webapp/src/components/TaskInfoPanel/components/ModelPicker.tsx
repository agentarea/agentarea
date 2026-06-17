"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import ModelBadge from "@/components/ui/model-badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  listModelInstancesAction,
  sendTaskCommandAction,
} from "@/lib/server-actions";

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
  const [models, setModels] = useState<any[]>([]);

  if (!isActive) {
    return null;
  }

  const handleOpen = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const { data } = await listModelInstancesAction({ is_active: true });
      setModels(data || []);
      setOpen(true);
    } catch {
      // ignore
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
    try {
      await sendTaskCommandAction(agentId, taskId, {
        command: "change_model",
        model_instance_id: modelInstanceId,
      });
    } finally {
      setSubmitting(false);
      setOpen(false);
    }
  };

  return (
    <div className="flex items-center gap-2 mt-1">
      {open ? (
        <div className="flex items-center gap-2 w-full">
          <Select onValueChange={handleSelect} defaultValue={currentModelId}>
            <SelectTrigger className="h-7 text-xs">
              <SelectValue placeholder="Select model" />
            </SelectTrigger>
            <SelectContent>
              {models.map((model: any) => (
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
            Cancel
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
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            "Change"
          )}
        </Button>
      )}
    </div>
  );
}
