import { getTranslations } from "next-intl/server";
import { LayoutDashboardIcon, TablePropertiesIcon } from "lucide-react";
import HeaderTabs from "@/components/HeaderTabs";

export default async function MCPHeaderTabs() {
  const t = await getTranslations("Common");

  return (
    <HeaderTabs
      tabs={[
        {
          value: "grid",
          label: t("grid"),
          icon: <LayoutDashboardIcon className="h-4 w-4" />,
        },
        {
          value: "table",
          label: t("table"),
          icon: <TablePropertiesIcon className="h-4 w-4" />,
        },
      ]}
      paramName="tab"
      defaultTab="grid"
    />
  );
}
