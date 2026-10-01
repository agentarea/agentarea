"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import HeaderTabs from "@/components/HeaderTabs";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { setCookie } from "@/utils/cookies";
import { MODELS_VIEW_COOKIE, resolveViewMode } from "./viewMode";

/**
 * Grid/table toggle in the shared models header. Controlled rather than the
 * HeaderTabs default, whose cookie is per path: both tabs share one choice.
 * The last pick is kept in state too, because this stays mounted across tab
 * switches and a link without `?tab=` must not fall back to a stale value.
 */
export default function ProviderHeaderTabs({
  initialView,
}: {
  initialView: string;
}) {
  const t = useTranslations("Common");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();
  const [lastView, setLastView] = useState(initialView);

  const view = resolveViewMode(searchParams.get("tab"), lastView);

  return (
    <HeaderTabs
      tabs={[
        { value: "table", label: t("table") },
        { value: "grid", label: t("grid") },
      ]}
      value={view}
      onChange={(next) => {
        setLastView(next);
        setCookie(MODELS_VIEW_COOKIE, next);
        const params = new URLSearchParams(searchParams.toString());
        params.set("tab", next);
        router.push(`${pathname}?${params.toString()}`, { scroll: false });
      }}
    />
  );
}
