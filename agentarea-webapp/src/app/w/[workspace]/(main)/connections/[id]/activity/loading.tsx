import { getTranslations } from "next-intl/server";
import { TableSkeleton } from "@/components/Skeleton";

/** The audit table the Activity tab draws, while it loads. */
export default async function Loading() {
  const t = await getTranslations("AuditLogPage");
  return (
    <div className="h-full overflow-y-auto px-4 py-5">
      <TableSkeleton
        rows={6}
        columns={[
          { header: "", barClassName: "h-4 w-4" },
          { header: t("table.action"), barClassName: "h-4 w-28" },
          { header: t("table.details"), barClassName: "h-4 w-40" },
          { header: t("table.actor"), barClassName: "h-4 w-24" },
          { header: t("table.ip"), barClassName: "h-4 w-20" },
          { header: t("table.when"), barClassName: "h-4 w-24" },
        ]}
      />
    </div>
  );
}
