"use client";

import { useTranslations } from "next-intl";
import { Grid2x2, Share2 } from "lucide-react";
import HeaderTabs from "@/components/HeaderTabs";

/** URL param holding the Access view; the explorer reads it back. */
export const ACCESS_VIEW_PARAM = "mode";

export type AccessView = "matrix" | "relationships";

export function parseAccessView(value: string | null | undefined): AccessView {
  return value === "matrix" ? "matrix" : "relationships";
}

/** Matrix / Relationships switch of the Access tab, in the page subheader. */
export default function AccessViewTabs() {
  const t = useTranslations("PoliciesPage.accessView");

  return (
    <HeaderTabs
      tabs={[
        {
          value: "matrix",
          label: t("matrix"),
          icon: <Grid2x2 className="h-4 w-4" />,
        },
        {
          value: "relationships",
          label: t("relationships"),
          icon: <Share2 className="h-4 w-4" />,
        },
      ]}
      paramName={ACCESS_VIEW_PARAM}
      defaultTab="relationships"
    />
  );
}
