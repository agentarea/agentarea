"use client";

import { ArrowDownAZ, Clock, Layers, Rows3 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import DisplayMenu from "@/components/DisplayMenu/DisplayMenu";

export default function TriggersDisplayMenu({
  currentGroup,
  currentOrder,
}: {
  currentGroup: "channel" | "none";
  currentOrder: "name" | "created";
}) {
  const t = useTranslations("TriggersPage");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const updateParam = (key: string, value: string, defaultValue?: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (defaultValue != null && value === defaultValue) params.delete(key);
    else params.set(key, value);
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
              onSelect: () => updateParam("group", "channel", "channel"),
            },
            {
              key: "none",
              icon: <Rows3 className="h-3.5 w-3.5" />,
              label: t("group.none"),
              selected: currentGroup === "none",
              onSelect: () => updateParam("group", "none", "channel"),
            },
          ],
        },
        {
          key: "ordering",
          label: t("display.ordering"),
          items: [
            {
              key: "name",
              icon: <ArrowDownAZ className="h-3.5 w-3.5" />,
              label: t("display.name"),
              selected: currentOrder === "name",
              onSelect: () => updateParam("order", "name", "name"),
            },
            {
              key: "created",
              icon: <Clock className="h-3.5 w-3.5" />,
              label: t("display.created"),
              selected: currentOrder === "created",
              onSelect: () => updateParam("order", "created", "name"),
            },
          ],
        },
      ]}
    />
  );
}
