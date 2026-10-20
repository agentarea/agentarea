"use client";

import type { ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { CalendarClock, Info } from "lucide-react";
import {
  FactRow,
  SectionCard,
  SectionCardHead,
  SoftTile,
} from "@/components/Overview/OverviewCard";
import { CopyableText } from "@/components/ui/copyable-text";

/** A labelled value inside a section card: a URL, a command, an image. */
export function CardField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5 border-b border-border/60 px-[15px] py-3 last:border-b-0">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

/** The "Details" card of a connection overview: its id and when it changed. */
export function ConnectionDetailsCard({
  id,
  createdAt,
  updatedAt,
}: {
  id: string;
  createdAt: string;
  updatedAt: string;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.details");
  const format = useFormatter();
  const dateTime = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });

  return (
    <SectionCard>
      <SectionCardHead icon={<Info />} title={t("title")} />
      <CardField label={t("id")}>
        <CopyableText text={id} />
      </CardField>
      <FactRow
        tile={<SoftTile icon={<CalendarClock />} />}
        title={dateTime(createdAt)}
        sub={t("created")}
      />
      <FactRow
        tile={<SoftTile icon={<CalendarClock />} />}
        title={dateTime(updatedAt)}
        sub={t("updated")}
      />
    </SectionCard>
  );
}
