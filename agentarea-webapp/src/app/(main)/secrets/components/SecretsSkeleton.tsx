import { useTranslations } from "next-intl";
import { TableSkeleton } from "@/components/Skeleton";

// Matches SecretsTable: Name · Description · Belongs to · Updated · actions.
export default function SecretsSkeleton() {
  const t = useTranslations("SecretsPage.table");

  return (
    <TableSkeleton
      rows={8}
      columns={[
        { header: t("name"), barClassName: "h-4 w-32" },
        { header: t("description"), barClassName: "h-4 w-40" },
        { header: t("belongsTo"), barClassName: "h-4 w-36" },
        {
          header: t("updated"),
          headerClassName: "w-[120px]",
          barClassName: "h-3 w-20",
        },
        { header: "", headerClassName: "w-0", barClassName: "hidden" },
      ]}
    />
  );
}
