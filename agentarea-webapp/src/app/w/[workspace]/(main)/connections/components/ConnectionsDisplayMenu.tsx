"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Activity, Layers, Rows3 } from "lucide-react";
import DisplayMenu from "@/components/DisplayMenu";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
import type { ConnectionGroupBy } from "../list-sections";

const GROUP_ICONS: Record<ConnectionGroupBy, typeof Layers> = {
  state: Activity,
  type: Layers,
  none: Rows3,
};

const GROUP_LABELS: Record<ConnectionGroupBy, "byState" | "byType" | "none"> = {
  state: "byState",
  type: "byType",
  none: "none",
};

/** URL-param driven "Display" menu (grouping) for the Connections listing. */
export default function ConnectionsDisplayMenu({
  currentGroup,
}: {
  currentGroup: ConnectionGroupBy;
}) {
  const t = useTranslations("MCPServersPage.group");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const onChange = (value: ConnectionGroupBy) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "state") params.delete("group");
    else params.set("group", value);
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <DisplayMenu>
      <MenuSectionLabel>{t("grouping")}</MenuSectionLabel>
      {(Object.keys(GROUP_ICONS) as ConnectionGroupBy[]).map((value) => {
        const Icon = GROUP_ICONS[value];
        return (
          <MenuRow
            key={value}
            icon={<Icon className="h-3.5 w-3.5" />}
            label={t(GROUP_LABELS[value])}
            selected={currentGroup === value}
            onClick={() => onChange(value)}
          />
        );
      })}
    </DisplayMenu>
  );
}
