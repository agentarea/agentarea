import { getTranslations } from "next-intl/server";
import { TableSkeleton } from "@/components/Skeleton";

// ProcessorsTable's columns.
export default async function Loading() {
  const t = await getTranslations("EventsPage");
  return (
    <div className="min-w-0 flex-1 px-4 py-5" aria-hidden="true">
      <TableSkeleton
        rows={2}
        columns={[
          { header: t("processors.writesTo"), barClassName: "h-4 w-40" },
          {
            header: t("streamPage.takes"),
            headerClassName: "w-[260px]",
            barClassName: "h-3.5 w-32",
          },
          {
            header: t("streams.created"),
            headerClassName: "w-[140px]",
            barClassName: "h-3.5 w-20",
          },
        ]}
      />
    </div>
  );
}
