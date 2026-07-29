"use client";

import { Layers, Rows3 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import DisplayMenu from "@/components/DisplayMenu/DisplayMenu";

export default function TriggersDisplayMenu({
  currentGroup,
}: {
  currentGroup: "channel" | "none";
}) {
  const t = useTranslations("TriggersPage");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const onGroupChange = (value: "channel" | "none") => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "channel") params.delete("group");
    else params.set("group", value);
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <DisplayMenu
      label={t("display.display")}
      sections={[
        {
          key: "grouping",
          label: t("display.grouping"),
          items: [
            {
              key: "channel",
              icon: <Layers className="h-3.5 w-3.5" />,
              label: t("group.byChannel"),
              selected: currentGroup === "channel",
              onSelect: () => onGroupChange("channel"),
            },
            {
              key: "none",
              icon: <Rows3 className="h-3.5 w-3.5" />,
              label: t("group.none"),
              selected: currentGroup === "none",
              onSelect: () => onGroupChange("none"),
            },
          ],
        },
      ]}
    />
  );
}
