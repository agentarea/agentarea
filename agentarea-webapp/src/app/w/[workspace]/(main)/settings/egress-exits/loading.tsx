import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { TableSkeleton } from "@/components/Skeleton";

// Shown while the page reads the exits. Keeps the real breadcrumb; the table
// is skeletoned in the shape EgressExitsClient draws.
export default async function EgressExitsLoading() {
  const [t, tSettings] = await Promise.all([
    getTranslations("EgressExits"),
    getTranslations("SettingsPage"),
  ]);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: tSettings("title"), href: "/settings" },
          { label: t("title") },
        ],
        description: t("description"),
      }}
    >
      <TableSkeleton
        rows={4}
        columns={[
          { header: t("table.name"), barClassName: "h-4 w-32" },
          { header: t("table.proxy"), barClassName: "h-4 w-48" },
          {
            header: t("table.credentials"),
            headerClassName: "w-[200px]",
            barClassName: "h-4 w-20",
          },
          { header: "", headerClassName: "w-0", barClassName: "hidden" },
        ]}
      />
    </ContentBlock>
  );
}
