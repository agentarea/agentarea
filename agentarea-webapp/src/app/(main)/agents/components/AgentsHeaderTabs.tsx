import { getTranslations } from "next-intl/server";
import HeaderTabs from "@/components/HeaderTabs";

export default async function AgentHeaderTabs({
  currentTab,
}: {
  currentTab?: string;
}) {
  const t = await getTranslations("Common");

  return (
    <HeaderTabs
      tabs={[
        { value: "table", label: t("table") },
        { value: "grid", label: t("grid") },
      ]}
      paramName="tab"
      defaultTab="grid"
      currentTab={currentTab}
    />
  );
}
