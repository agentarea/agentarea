import React from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, LayoutTemplate } from "lucide-react";
import type { AgentPresetResponse } from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { cn } from "@/lib/utils";

type PresetPickerProps = {
  /** `null` when the presets could not be loaded. */
  presets: AgentPresetResponse[] | null;
  /** Id of the applied preset; `null` is Empty. */
  selectedId: string | null;
  onSelect: (preset: AgentPresetResponse | null) => void;
};

const PresetPicker = ({ presets, selectedId, onSelect }: PresetPickerProps) => {
  const t = useTranslations("AgentsPage.create.presets");

  if (presets === null) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {t("loadFailed")}
      </p>
    );
  }
  if (presets.length === 0) return null;

  const selected = presets.find((preset) => preset.id === selectedId);
  const options = [
    { id: null, name: t("empty"), description: t("emptyDescription") },
    ...presets.map((preset) => ({
      id: preset.id,
      name: preset.name,
      description: preset.description,
    })),
  ];

  return (
    <div className="space-y-2">
      <FormLabel icon={LayoutTemplate}>{t("title")}</FormLabel>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {options.map((option) => {
          const isSelected = option.id === selectedId;
          return (
            <button
              key={option.id ?? "empty"}
              type="button"
              aria-pressed={isSelected}
              onClick={() =>
                onSelect(presets.find((p) => p.id === option.id) ?? null)
              }
              className={cn(
                "rounded-md border px-3 py-2 text-left transition-colors",
                isSelected
                  ? "border-primary bg-primary/5"
                  : "hover:bg-muted/50"
              )}
            >
              <p className="truncate text-sm font-medium">{option.name}</p>
              {option.description && (
                <p className="line-clamp-2 text-xs text-muted-foreground">
                  {option.description}
                </p>
              )}
            </button>
          );
        })}
      </div>
      {!!selected?.unavailable_skills?.length && (
        <p className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-500">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t("unavailableSkills", {
            skills: selected.unavailable_skills.join(", "),
          })}
        </p>
      )}
    </div>
  );
};

export default PresetPicker;
