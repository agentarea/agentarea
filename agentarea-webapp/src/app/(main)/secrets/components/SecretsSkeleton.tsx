import { useTranslations } from "next-intl";
import { TableSkeleton } from "@/components/Skeleton";

// Matches SecretsTable: name · description · used by · updated · actions.
export default function SecretsSkeleton() {
  const t = useTranslations("SecretsPage.table");

  return (
    <TableSkeleton
      rows={8}
      columns={[
        { header: t("name"), barClassName: "h-4 w-32" },
        {
          header: t("description"),
          cellClassName: "max-w-[300px]",
          barClassName: "h-3 w-48",
        },
        {
          header: t("usedBy"),
          headerClassName: "w-[30%]",
          barClassName: "h-3 w-40",
        },
        {
          header: t("updated"),
          headerClassName: "w-[150px]",
          barClassName: "h-3 w-24",
        },
        { header: "", headerClassName: "w-0", barClassName: "hidden" },
      ]}
    />
  );
}
