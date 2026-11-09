"use client";

import { useFormatter, useTranslations } from "next-intl";
import { CalendarClock, Info } from "lucide-react";
import {
  CardField,
  FactRow,
  SectionCard,
  SectionCardHead,
  SoftTile,
} from "@/components/Overview/OverviewCard";
import { CopyableText } from "@/components/ui/copyable-text";

/** The "Details" card of a detail page's overview: the id and when it changed. */
export function DetailsCard({
  id,
  idLabel,
  createdAt,
  updatedAt,
}: {
  id: string;
  idLabel: string;
  createdAt?: string;
  updatedAt?: string;
}) {
  const t = useTranslations("DetailsCard");
  const format = useFormatter();
  const dateTime = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });

  return (
    <SectionCard>
      <SectionCardHead icon={<Info />} title={t("title")} />
      <CardField label={idLabel}>
        <CopyableText text={id} />
      </CardField>
      {createdAt && (
        <FactRow
          tile={<SoftTile icon={<CalendarClock />} />}
          title={dateTime(createdAt)}
          sub={t("created")}
        />
      )}
      {updatedAt && (
        <FactRow
          tile={<SoftTile icon={<CalendarClock />} />}
          title={dateTime(updatedAt)}
          sub={t("updated")}
        />
      )}
    </SectionCard>
  );
}
