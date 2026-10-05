"use client";

import { useTranslations } from "next-intl";
import HeaderTabs from "./HeaderTabs";

/**
 * The table / grid switcher of a list page's subheader. Drives the `tab` URL
 * param and remembers the choice per page in a cookie (see `HeaderTabs`).
 */
export default function ViewModeTabs({
  currentTab,
  defaultTab = "grid",
}: {
  currentTab?: string;
  defaultTab?: "grid" | "table";
}) {
  const t = useTranslations("Common");

  return (
    <HeaderTabs
      tabs={[
        { value: "table", label: t("table") },
        { value: "grid", label: t("grid") },
      ]}
      paramName="tab"
      defaultTab={defaultTab}
      currentTab={currentTab}
    />
  );
}
