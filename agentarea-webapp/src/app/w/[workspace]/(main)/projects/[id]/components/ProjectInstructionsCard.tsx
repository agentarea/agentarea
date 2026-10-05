"use client";

import { useTranslations } from "next-intl";
import { FileText } from "lucide-react";
import { InfoPanelExpandableText } from "@/components/InfoPanel";
import {
  EmptyRow,
  SectionCard,
  SectionCardHead,
} from "@/components/Overview/OverviewCard";

/** The project's standing instructions, folded to six lines, with a way to edit them. */
export default function ProjectInstructionsCard({
  projectId,
  instructions,
}: {
  projectId: string;
  instructions: string | null;
}) {
  const t = useTranslations("ProjectOverviewPage");
  const settingsHref = `/projects/${projectId}/settings`;

  return (
    <SectionCard>
      <SectionCardHead
        icon={<FileText />}
        title={t("instructions")}
        link={{ label: t("edit"), href: settingsHref }}
      />
      {instructions ? (
        <InfoPanelExpandableText
          content={instructions}
          maxLines={6}
          className="px-[15px] py-3"
          textClassName="text-[12.5px] leading-5 text-muted-foreground"
        />
      ) : (
        <EmptyRow
          text={t("noInstructions")}
          action={{ label: t("addInstructions"), href: settingsHref }}
        />
      )}
    </SectionCard>
  );
}
