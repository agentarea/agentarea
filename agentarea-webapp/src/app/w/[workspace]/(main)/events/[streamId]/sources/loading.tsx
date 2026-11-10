import { getTranslations } from "next-intl/server";
import { TableSkeleton } from "@/components/Skeleton";

// StreamSourcesTable's columns, the first bar as tall as the 28px tile.
export default async function Loading() {
  const t = await getTranslations("EventsPage.streamPage");
  return (
    <div className="min-w-0 flex-1 px-4 py-5" aria-hidden="true">
      <TableSkeleton
        rows={3}
        columns={[
          { header: t("source"), barClassName: "h-7 w-48 rounded-md" },
          {
            header: t("delivery"),
            headerClassName: "hidden w-[140px] md:table-cell",
            cellClassName: "hidden md:table-cell",
            barClassName: "h-3.5 w-16",
          },
          {
            header: t("address"),
            headerClassName: "hidden w-[340px] lg:table-cell",
            cellClassName: "hidden lg:table-cell",
            barClassName: "h-3.5 w-56",
          },
          {
            header: t("state"),
            headerClassName: "w-[200px]",
            barClassName: "h-3.5 w-20",
          },
          { header: "", headerClassName: "w-[110px]", barClassName: "h-0" },
        ]}
      />
    </div>
  );
}
