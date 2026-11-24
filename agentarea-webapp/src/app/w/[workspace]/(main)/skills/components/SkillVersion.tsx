"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getSkillUpdateStatusPresentation } from "@/lib/status";
import type { Skill } from "@/types/skill";
import UpdateSkillButton from "./UpdateSkillButton";

// The catalog's moving pointer: it names no version a reader can compare.
const UNPINNED = "latest";

function label(version: string): string {
  if (/^[0-9a-f]{40}$/.test(version)) return version.slice(0, 7);
  return /^\d/.test(version) ? `v${version}` : version;
}

/**
 * The version a skill runs. A catalog install shows its catalog version and,
 * when the registry has moved on, the version waiting and the way to take it;
 * a skill written here shows its saved revision.
 */
export default function SkillVersion({
  skill,
  onUpdated,
}: {
  skill: Pick<
    Skill,
    | "id"
    | "name"
    | "version"
    | "latest_version"
    | "update_available"
    | "revision"
  >;
  onUpdated: () => void;
}) {
  const t = useTranslations("SkillsPage.update");
  const [error, setError] = useState<string | null>(null);
  if (!skill.version || skill.version === UNPINNED) {
    // A skill saved before versions were recorded has none; what it runs is its first.
    return (
      <span className="whitespace-nowrap text-[11.5px] tabular-nums text-muted-foreground">
        v{Math.max(skill.revision ?? 0, 1)}
      </span>
    );
  }
  const update = getSkillUpdateStatusPresentation(skill);

  if (!update || !skill.latest_version) {
    return (
      <span className="whitespace-nowrap text-[11.5px] tabular-nums text-muted-foreground">
        {label(skill.version)}
      </span>
    );
  }

  return (
    // Its own controls: a click here must not open the skill behind the row.
    <span
      className="inline-flex items-center gap-2"
      onClick={(event) => event.stopPropagation()}
    >
      <StatusIndicator
        kind={update.kind}
        size="sm"
        className="whitespace-nowrap tabular-nums"
        title={t("available")}
      >
        {label(skill.version)} → {label(skill.latest_version)}
      </StatusIndicator>
      <UpdateSkillButton
        skill={skill}
        onUpdated={onUpdated}
        onError={setError}
      />
      {error && (
        <span
          className="max-w-[200px] truncate text-[11.5px] text-destructive"
          title={error}
        >
          {error}
        </span>
      )}
    </span>
  );
}
