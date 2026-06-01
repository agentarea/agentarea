"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useInfiniteList } from "@/hooks/useInfiniteList";
import { listSkillsAction } from "@/lib/server-actions";
import type { PaginatedSkills, Skill } from "@/types/skill";
import SkillsCard from "./SkillsCard";
import SkillsTable from "./SkillsTable";

const PAGE_SIZE = 20;

interface SkillsListProps {
  viewMode: "grid" | "table";
  searchQuery: string;
  sourceType: string;
  hasFiles?: boolean;
  networkScope: string;
}

export default function SkillsList({
  viewMode,
  searchQuery,
  sourceType,
  hasFiles,
  networkScope,
}: SkillsListProps) {
  const router = useRouter();
  const t = useTranslations("SkillsPage");

  const fetchPage = useCallback(
    async (params: { page: number; page_size: number; search?: string }) => {
      const { data } = await listSkillsAction({
        page: params.page,
        page_size: params.page_size,
        search: params.search,
        source_type: sourceType || undefined,
        has_files: hasFiles,
        network_scope: networkScope || undefined,
        paginated: true,
      });
      const result = (data as PaginatedSkills | null) ?? {
        items: [],
        total: 0,
        has_next: false,
      };
      return {
        items: result.items,
        total: result.total,
        has_next: result.has_next,
      };
    },
    [sourceType, hasFiles, networkScope]
  );

  const {
    items: skills,
    isLoading,
    isFetchingMore,
    hasMore,
    error,
    sentinelRef,
  } = useInfiniteList<Skill>({
    fetchPage,
    pageSize: PAGE_SIZE,
    search: searchQuery || undefined,
    resetKey: JSON.stringify({ sourceType, hasFiles, networkScope }),
  });

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        {t("error.loadSkills") || "Error loading skills"}
      </div>
    );
  }

  const hasSkills = skills.length > 0;
  const hasActiveFilters =
    Boolean(searchQuery) ||
    Boolean(sourceType) ||
    hasFiles !== undefined ||
    Boolean(networkScope);

  if (!hasSkills && !hasActiveFilters) {
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

  if (!hasSkills && hasActiveFilters) {
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

      {hasMore && (
        <div ref={sentinelRef} className="flex justify-center py-6">
          {isFetchingMore && (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          )}
        </div>
      )}
    </>
  );
}
