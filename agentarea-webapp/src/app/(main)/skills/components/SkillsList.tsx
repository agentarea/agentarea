"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import EmptyState from "@/components/EmptyState";
import SkillsTable from "./SkillsTable";
import SkillsCard from "./SkillsCard";
import type { Skill } from "@/types/skill";

interface SkillsListProps {
  skills: Skill[];
  viewMode: "grid" | "table";
  searchQuery: string;
}

export default function SkillsList({
  skills,
  viewMode,
  searchQuery,
}: SkillsListProps) {
  const router = useRouter();
  const t = useTranslations("SkillsPage");

  const hasSkills = skills.length > 0;

  if (!hasSkills && !searchQuery) {
    return (
      <EmptyState
        title={t("noSkills")}
        description={t("noSkillsDescription")}
        iconsType="skills"
        action={{
          label: t("addSkill"),
          onClick: () => router.push("/skills/create"),
        }}
      />
    );
  }

  if (!hasSkills && searchQuery) {
    return (
      <EmptyState
        title={t("noMatchingSkills", { query: searchQuery })}
        description={t("noMatchingSkillsDescription")}
        iconsType="skills"
        action={{
          label: t("clearSearch"),
          onClick: () => router.push("/skills"),
        }}
      />
    );
  }

  return (
    <>
      {viewMode === "grid" ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {skills.map((skill) => (
            <SkillsCard key={skill.id} skill={skill} />
          ))}
        </div>
      ) : (
        <SkillsTable skills={skills} />
      )}
    </>
  );
}
