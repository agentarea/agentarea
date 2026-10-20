import { useTranslations } from "next-intl";
import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import { CARD_GRID_LOOSE } from "@/lib/collectionGrids";

function SavedTaskCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle lines={1} />;
}

export default function SavedTasksSkeleton({
  viewMode,
}: {
  viewMode?: string;
}) {
  const t = useTranslations("SavedTasksPage.columns");

  // The table columns of SavedTasksContent.
  const columns: SkeletonColumn[] = [
    { header: t("name"), barClassName: "h-4 w-48" },
    { header: t("agent"), barClassName: "h-4 w-28" },
    { header: t("updated"), barClassName: "h-3.5 w-12" },
  ];

  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={columns}
      gridClassName={CARD_GRID_LOOSE}
      count={8}
      Card={SavedTaskCardSkeleton}
    />
  );
}
