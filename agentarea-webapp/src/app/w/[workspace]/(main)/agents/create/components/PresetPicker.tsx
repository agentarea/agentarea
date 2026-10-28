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
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";

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
    id: string | null,
    title: string,
    icon: React.ReactNode,
    description: string | null | undefined,
    contents?: React.ReactNode
  ) => {
    const isSelected = id === selectedId;
    return (
      <ChoiceTile
        key={id ?? "empty"}
        className="h-full py-2.5"
        title={
          <span className="flex items-center gap-1.5">
            <span className="truncate">{title}</span>
            {isSelected && (
              <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
            )}
          </span>
        }
        // The description cut at two lines, whole on hover; what the preset
        // brings on a line of its own, so the name keeps its width.
        description={
          description ? (
            <span title={description}>{description}</span>
          ) : undefined
        }
        footer={contents}
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
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {tile(
          null,
          t("empty"),
          <EntityAvatar
            variant="soft"
            size={28}
            iconScale={0.5}
            icon={<FilePlus2 strokeWidth={1.85} />}
            aria-hidden
          />,
          t("emptyDescription")
        )}
        {presets.map((preset) =>
          tile(
            preset.id,
            preset.name,
            <EntityAvatar
              hue={deterministicHue(preset.id)}
              size={28}
              iconScale={0.5}
              icon={<LayoutTemplate strokeWidth={1.85} />}
              aria-hidden
            />,
            preset.description,
            <PresetContents preset={preset} />
          )
        )}
      </div>
      {filled.length > 0 && (
        <p className="note" role="status">
          {t("filledLine", { items: filled.join(", ") })}
        </p>
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
