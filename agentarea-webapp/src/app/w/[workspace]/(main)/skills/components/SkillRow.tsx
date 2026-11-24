"use client";

import { useTranslations } from "next-intl";
import { Copy } from "lucide-react";
import { SkillTile } from "@/components/SkillTile";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import type { Skill } from "@/types/skill";
import SkillProvenance from "./SkillProvenance";
import SkillVersion from "./SkillVersion";

interface SkillRowProps {
  skill: Skill;
  onUpdated: () => void;
}

export default function SkillRow({ skill, onUpdated }: SkillRowProps) {
  const router = useWorkspaceRouter();
  const t = useTranslations("SkillsPage");

  const open = () => router.push(`/skills/${skill.id}`);

  return (
    <InteractiveListRow
      onClick={open}
      start={<SkillTile skillId={skill.id} variant="row" />}
      contentClassName="gap-3"
      end={
        <>
          <SkillProvenance skill={skill} />
          <span className="flex min-w-[56px] justify-end">
            <SkillVersion skill={skill} onUpdated={onUpdated} />
          </span>
          <span className="skill-col-agents w-[76px] text-right text-[11.5px] tabular-nums text-muted-foreground">
            {t("agentCount", { count: skill.agent_count ?? 0 })}
          </span>
        </>
      }
      hoverActions={
        <button
          type="button"
          title={t("rowActions.duplicate")}
          aria-label={t("rowActions.duplicate")}
          onClick={() => router.push(`/skills/create?from=${skill.id}`)}
          className="grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:bg-zinc-700 max-[767px]:h-11 max-[767px]:w-11"
        >
          <Copy className="h-[15px] w-[15px]" />
        </button>
      }
    >
      <>
        <span className="max-w-[230px] shrink-0 truncate text-[13px] font-medium text-foreground max-[767px]:max-w-[130px] max-[767px]:shrink">
          {skill.name}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">
          {skill.description || ""}
        </span>
      </>
    </InteractiveListRow>
  );
}
