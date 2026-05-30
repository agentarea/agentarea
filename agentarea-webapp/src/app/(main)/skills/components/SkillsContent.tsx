import { getTranslations } from "next-intl/server";
import { listSkills } from "@/lib/api";
import type { PaginatedSkills } from "@/types/skill";
import SkillsList from "./SkillsList";

const PAGE_SIZE = 20;

interface SkillsContentProps {
  viewMode: "grid" | "table";
  searchQuery: string;
  page: number;
  sourceType: string;
  hasFiles?: boolean;
  networkScope: string;
}

export default async function SkillsContent({
  viewMode,
  searchQuery,
  page,
  sourceType,
  hasFiles,
  networkScope,
}: SkillsContentProps) {
  const t = await getTranslations("SkillsPage");

  const { data, error } = await listSkills({
    page,
    page_size: PAGE_SIZE,
    search: searchQuery.trim() || undefined,
    source_type: sourceType || undefined,
    has_files: hasFiles,
    network_scope: networkScope || undefined,
    paginated: true,
  });

  if (error) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        {t("error.loadSkills") || "Error loading skills"}
      </div>
    );
  }

  const result = (data as PaginatedSkills | null) || {
    items: [],
    total: 0,
    page,
    page_size: PAGE_SIZE,
    has_next: false,
  };

  return (
    <SkillsList
      skills={result.items}
      viewMode={viewMode}
      searchQuery={searchQuery}
      page={result.page}
      pageSize={result.page_size}
      total={result.total}
    />
  );
}
