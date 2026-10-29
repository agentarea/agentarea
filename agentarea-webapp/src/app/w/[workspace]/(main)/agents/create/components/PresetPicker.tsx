import React, { useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  FilePlus2,
  LayoutTemplate,
  type LucideIcon,
} from "lucide-react";
import type { AgentPresetResponse } from "@/api/client/types.gen";
import { ChoiceTile } from "@/components/ChoiceTile";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
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

/**
 * Two rows of tiles before "show all": four while the grid is one or two
 * columns wide, six at three. The Empty tile counts as one.
 */
const SHOWN_NARROW = 4;
const SHOWN_WIDE = 6;

/** Which tiles wait behind "show all", by their place in the grid. */
function hiddenUntilExpanded(index: number) {
  if (index >= SHOWN_WIDE) return "hidden";
  if (index >= SHOWN_NARROW) return "hidden lg:block";
  return undefined;
}

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
  const [expanded, setExpanded] = useState(false);

  if (presets === null) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {t("loadFailed")}
      </p>
    );
  }
  if (presets.length === 0) return null;

  const selected = presets.find((preset) => preset.id === selectedId);
  // What picking a preset puts into the form, in words, for its tooltip.
  const fillsOf = (preset: AgentPresetResponse) =>
    [
      preset.instruction ? t("filledInstruction") : null,
      ...CONTENTS.map(({ key }) =>
        preset[key].length
          ? t(`filled.${key}`, { count: preset[key].length })
          : null
      ),
    ].filter(Boolean);

  const tile = (
    id: string,
    title: string,
    icon: React.ReactNode,
    description: string | null | undefined,
    contents: React.ReactNode,
    fills: (string | null)[],
    index: number
  ) => {
    const isSelected = id === selectedId;
    return (
      <Tooltip key={id} delayDuration={300}>
        <TooltipTrigger asChild>
          {/* The tile keeps its button; the wrapper only anchors the tooltip.
              The picked preset stays in sight even past the fold. */}
          <div
            className={cn(
              "min-w-0",
              !expanded && !isSelected && hiddenUntilExpanded(index)
            )}
          >
            <ChoiceTile
              className="w-full items-center py-2"
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
                  <span className="min-w-0 flex-1 truncate">{description}</span>
                  {contents && <span className="shrink-0">{contents}</span>}
                </span>
              }
              icon={icon}
              selected={isSelected}
              onClick={() => onSelect(presets.find((p) => p.id === id) ?? null)}
            />
          </div>
        </TooltipTrigger>
        {/* The whole description, and what picking it puts in the form. */}
        <TooltipContent className="max-w-xs space-y-1">
          {description && <p>{description}</p>}
          {fills.length > 0 && (
            <p className="opacity-70">
              {t("willFill", { items: fills.join(", ") })}
            </p>
          )}
        </TooltipContent>
      </Tooltip>
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <FormLabel icon={LayoutTemplate}>{t("title")}</FormLabel>
        <span className="note">{t("hint")}</span>
      </div>
      <TooltipProvider>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {/* Empty is no preset at all: the first tile, picked while nothing
              else is. */}
          <ChoiceTile
            className="items-center py-2"
            icon={
              <EntityAvatar
                variant="soft"
                size={24}
                iconScale={0.5}
                icon={<FilePlus2 strokeWidth={1.85} />}
                aria-hidden
              />
            }
            title={
              <span className="flex items-center gap-1.5">
                <span className="truncate">{t("reset")}</span>
                {!selected && (
                  <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
                )}
              </span>
            }
            description={
              <span className="block truncate">{t("emptyDescription")}</span>
            }
            selected={!selected}
            onClick={() => onSelect(null)}
          />
          {presets.map((preset, index) =>
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
              <PresetContents preset={preset} />,
              fillsOf(preset),
              index + 1
            )
          )}
        </div>
      </TooltipProvider>
      {presets.length + 1 > SHOWN_NARROW && (
        <Button
          type="button"
          variant="ghost"
          size="xs"
          // Three columns fit six tiles in two rows; below that, four.
          className={cn(
            "px-2 text-muted-foreground hover:text-foreground",
            presets.length + 1 <= SHOWN_WIDE && "lg:hidden"
          )}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
          {expanded ? t("showLess") : t("showAll", { count: presets.length })}
        </Button>
      )}
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
