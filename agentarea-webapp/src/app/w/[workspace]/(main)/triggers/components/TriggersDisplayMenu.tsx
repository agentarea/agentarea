"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Layers, Rows3 } from "lucide-react";
import DisplayMenu from "@/components/DisplayMenu";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";

/** URL-param driven "Display" menu (grouping) for the Automation listing. */
export default function TriggersDisplayMenu({
  currentGroup,
}: {
  currentGroup: string;
}) {
  const t = useTranslations("TriggersPage.group");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const onChange = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "channel") params.delete("group");
    else params.set("group", value);
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <DisplayMenu>
      <MenuSectionLabel>{t("grouping")}</MenuSectionLabel>
      <MenuRow
        icon={<Layers className="h-3.5 w-3.5" />}
        label={t("byChannel")}
        selected={currentGroup === "channel"}
        onClick={() => onChange("channel")}
      />
      <MenuRow
        icon={<Rows3 className="h-3.5 w-3.5" />}
        label={t("none")}
        selected={currentGroup === "none"}
        onClick={() => onChange("none")}
      />
    </DisplayMenu>
  );
}
