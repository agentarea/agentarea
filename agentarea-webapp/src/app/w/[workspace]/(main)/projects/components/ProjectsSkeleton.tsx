import { useTranslations } from "next-intl";
import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import { CARD_GRID_LOOSE } from "@/lib/collectionGrids";

// ProjectCard: icon + name, the description as subtitle, then the counts row.
function ProjectCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle lines={1} />;
}

export default function ProjectsSkeleton({ viewMode }: { viewMode?: string }) {
  const t = useTranslations("ProjectsPage");

  // The table columns of ProjectsContent.
  const columns: SkeletonColumn[] = [
    { header: t("columns.project"), barClassName: "h-4 w-40" },
    { header: t("columns.agents"), barClassName: "h-3.5 w-6" },
    { header: t("columns.skills"), barClassName: "h-3.5 w-6" },
    { header: t("columns.mcp"), barClassName: "h-3.5 w-6" },
    { header: t("columns.instructions"), barClassName: "h-3.5 w-8" },
  ];

  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={columns}
      gridClassName={CARD_GRID_LOOSE}
      count={8}
      Card={ProjectCardSkeleton}
    />
  );
}
