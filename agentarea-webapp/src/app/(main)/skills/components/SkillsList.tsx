"use client";

import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import type { Skill } from "@/types/skill";
import SkillsCard from "./SkillsCard";
import SkillsTable from "./SkillsTable";

interface SkillsListProps {
  skills: Skill[];
  viewMode: "grid" | "table";
  searchQuery: string;
  page: number;
  pageSize: number;
  total: number;
}

export default function SkillsList({
  skills,
  viewMode,
  searchQuery,
  page,
  pageSize,
  total,
}: SkillsListProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations("SkillsPage");

  const hasSkills = skills.length > 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const goToPage = (nextPage: number) => {
    const params = new URLSearchParams(searchParams.toString());
    if (nextPage <= 1) {
      params.delete("page");
    } else {
      params.set("page", String(nextPage));
    }
    const query = params.toString();
    router.push(query ? `/skills?${query}` : "/skills");
  };

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
      {totalPages > 1 && (
        <div className="mt-6 flex items-center justify-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => goToPage(page - 1)}
            disabled={page <= 1}
            aria-label={t("pagination.previous")}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground">
            {t("pagination.pageStatus", { page, totalPages })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => goToPage(page + 1)}
            disabled={page >= totalPages}
            aria-label={t("pagination.next")}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </>
  );
}
