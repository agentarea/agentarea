import { useTranslations } from "next-intl";
import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import { CARD_GRID_LOOSE } from "@/lib/collectionGrids";

// StreamCard: tile + name, the description as subtitle, then one meta line.
function StreamCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle lines={1} />;
}

export default function StreamsSkeleton({ viewMode }: { viewMode?: string }) {
  const t = useTranslations("EventsPage.streams");

  // The table columns of StreamsContent.
  const columns: SkeletonColumn[] = [
    { header: t("name"), barClassName: "h-7 w-56 rounded-md" },
    {
      header: t("writtenBy"),
      headerClassName: "hidden w-[200px] md:table-cell",
      cellClassName: "hidden md:table-cell",
      barClassName: "h-3.5 w-28",
    },
    {
      header: t("created"),
      headerClassName: "w-[120px]",
      barClassName: "h-3.5 w-14",
    },
  ];

  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={columns}
      gridClassName={CARD_GRID_LOOSE}
      count={8}
      Card={StreamCardSkeleton}
    />
  );
}
