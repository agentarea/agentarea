import { getTranslations } from "next-intl/server";
import { TableSkeleton } from "@/components/Skeleton";

// Matches ExecutionsTable: status (with an error line) · started · source ·
// duration · cost, with the hover actions taking no visible room.
export default async function Loading() {
  const t = await getTranslations("TriggersPage.detail");
  return (
    <div className="p-6">
      <TableSkeleton
        rows={10}
        columns={[
          {
            header: t("columnStatus"),
            headerClassName: "w-[220px]",
            barClassName: "h-4 w-24",
          },
          {
            header: t("columnStarted"),
            headerClassName: "w-[160px]",
            barClassName: "h-3 w-24",
          },
          {
            header: t("executionSource"),
            headerClassName: "hidden w-[200px] md:table-cell",
            cellClassName: "hidden md:table-cell",
            barClassName: "h-3 w-28",
          },
          {
            header: t("columnDuration"),
            headerClassName: "hidden w-[110px] text-right md:table-cell",
            cellClassName: "hidden md:table-cell",
            barClassName: "ml-auto h-3 w-12",
          },
          {
            header: t("cost"),
            headerClassName: "w-[100px] text-right",
            barClassName: "ml-auto h-3 w-12",
          },
          { header: "", headerClassName: "w-0", barClassName: "hidden" },
        ]}
      />
    </div>
  );
}
