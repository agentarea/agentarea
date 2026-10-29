import React from "react";
import { useTranslations } from "next-intl";
import {
  AlertTriangle,
  Check,
  FilePlus2,
  LayoutTemplate,
  type LucideIcon,
} from "lucide-react";
import type { AgentPresetResponse } from "@/api/client/types.gen";
import { ChoiceTile } from "@/components/ChoiceTile";
import FormLabel from "@/components/FormLabel/FormLabel";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";

type PresetPickerProps = {
  /** `null` when the presets could not be loaded. */
  presets: AgentPresetResponse[] | null;
  /** Id of the applied preset; `null` is Empty. */
  selectedId: string | null;
  onSelect: (preset: AgentPresetResponse | null) => void;
};

/** What a preset brings, in the order the form lists its sections. */
const CONTENTS: { key: "tools" | "skills" | "triggers"; icon: LucideIcon }[] = [
  { key: "tools", icon: ENTITY_ICONS.tool },
  { key: "skills", icon: ENTITY_ICONS.skill },
  { key: "triggers", icon: ENTITY_ICONS.trigger },
];

/** A preset's contents as glyphs with counts, e.g. 🔧 2 ✨ 1 ⚡ 1. */
function PresetContents({ preset }: { preset: AgentPresetResponse }) {
  const parts = CONTENTS.filter(({ key }) => preset[key].length > 0);
  if (!parts.length) return null;
  return (
    <span className="flex items-center gap-2.5 tabular-nums">
      {parts.map(({ key, icon: Icon }) => (
        <span key={key} className="flex items-center gap-1">
          <Icon className="h-3 w-3" aria-hidden />
          {preset[key].length}
        </span>
      ))}
    </span>
  );
}

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
  // What picking the preset put into the form, said once under the tiles.
  const filled = selected
    ? [
        selected.instruction ? t("filledInstruction") : null,
        ...CONTENTS.map(({ key }) =>
          selected[key].length
            ? t(`filled.${key}`, { count: selected[key].length })
            : null
        ),
      ].filter(Boolean)
    : [];

  const tile = (
    id: string,
    title: string,
    icon: React.ReactNode,
    description: string | null | undefined,
    contents?: React.ReactNode
  ) => {
    const isSelected = id === selectedId;
    return (
      <ChoiceTile
        key={id}
        className="items-center py-2"
        title={
          <span className="flex items-center gap-1.5">
            <span className="truncate">{title}</span>
            {isSelected && (
              <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
            )}
          </span>
        }
        // One line under the name: the description, whole on hover, and what
        // the preset brings at its end.
        description={
          <span className="flex items-center gap-2">
            <span
              className="min-w-0 flex-1 truncate"
              title={description ?? undefined}
            >
              {description}
            </span>
            {contents && <span className="shrink-0">{contents}</span>}
          </span>
        }
        icon={icon}
        selected={isSelected}
        onClick={() => onSelect(presets.find((p) => p.id === id) ?? null)}
      />
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <FormLabel icon={LayoutTemplate}>{t("title")}</FormLabel>
        <span className="note">{t("hint")}</span>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        {/* Empty is no preset at all: a square at the head of the row,
            picked while nothing else is; named in full on a phone, where the
            tiles stack, and on hover elsewhere. */}
        <TooltipProvider>
          <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-pressed={!selected}
                aria-label={t("reset")}
                onClick={() => onSelect(null)}
                className={cn(
                  "flex items-center gap-2.5 rounded-md border px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:shrink-0 sm:justify-center sm:px-0 sm:py-0 sm:w-12",
                  !selected
                    ? "border-primary bg-primary/5"
                    : "hover:bg-muted/50"
                )}
              >
                <EntityAvatar
                  variant="soft"
                  size={24}
                  iconScale={0.5}
                  color={!selected ? "hsl(var(--primary))" : undefined}
                  icon={<FilePlus2 strokeWidth={1.85} />}
                  aria-hidden
                />
                <span className="sm:hidden">{t("reset")}</span>
              </button>
            </TooltipTrigger>
            <TooltipContent>{t("reset")}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {presets.map((preset) =>
            tile(
              preset.id,
              preset.name,
              <EntityAvatar
                hue={deterministicHue(preset.id)}
                size={24}
                iconScale={0.5}
                icon={<LayoutTemplate strokeWidth={1.85} />}
                aria-hidden
              />,
              preset.description,
              <PresetContents preset={preset} />
            )
          )}
        </div>
      </div>
      {selected && (
        // The picked preset on a quiet plate under the tiles: what it is for,
        // what it put in, and any skill the catalog lacks, a line each.
        <div
          className="space-y-0.5 rounded-md bg-muted/50 px-3 py-2 text-xs leading-5 dark:bg-zinc-800/50"
          role="status"
        >
          {selected.description && (
            <p className="text-foreground/80">{selected.description}</p>
          )}
          {filled.length > 0 && (
            <p className="text-muted-foreground">
              {t("filledLine", { items: filled.join(", ") })}
            </p>
          )}
          {!!selected.unavailable_skills?.length && (
            <p className="flex items-center gap-1 text-amber-600 dark:text-amber-500">
              <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden />
              {t("unavailableSkills", {
                skills: selected.unavailable_skills.join(", "),
              })}
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default PresetPicker;
