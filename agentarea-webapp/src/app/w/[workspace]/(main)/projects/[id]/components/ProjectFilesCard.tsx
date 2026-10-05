"use client";

import { useFormatter, useTranslations } from "next-intl";
import { FileText, FolderOpen } from "lucide-react";
import type { ProjectFileInfo } from "@/api/client";
import FormError from "@/components/FormError";
import {
  EmptyRow,
  FactRow,
  SectionCard,
  SectionCardHead,
  SoftTile,
} from "@/components/Overview/OverviewCard";
import { formatFileSize } from "@/utils/fileUtils";

/** How many of the newest files the overview lists; the rest are a tab away. */
const MAX_FILES = 5;

/** The newest files of the project, with the way to all of them. */
export default function ProjectFilesCard({
  projectId,
  files,
  error,
}: {
  projectId: string;
  files: ProjectFileInfo[];
  error: string | null;
}) {
  const t = useTranslations("ProjectOverviewPage");
  const format = useFormatter();
  const filesHref = `/projects/${projectId}/files`;
  const newest = [...files]
    .sort((a, b) =>
      (b.last_modified ?? "").localeCompare(a.last_modified ?? "")
    )
    .slice(0, MAX_FILES);

  return (
    <SectionCard>
      <SectionCardHead
        icon={<FolderOpen />}
        title={t("files")}
        count={error ? undefined : files.length}
        link={{ label: t("allFiles"), href: filesHref }}
      />
      {error ? (
        <div className="px-[15px] py-3">
          <FormError>{error}</FormError>
        </div>
      ) : newest.length > 0 ? (
        newest.map((file) => (
          <FactRow
            key={file.path}
            tile={<SoftTile icon={<FileText />} />}
            title={file.path}
            sub={
              file.last_modified
                ? format.dateTime(new Date(file.last_modified), {
                    dateStyle: "medium",
                  })
                : undefined
            }
            trailing={
              <span className="tabular-nums">{formatFileSize(file.size)}</span>
            }
          />
        ))
      ) : (
        <EmptyRow
          text={t("noFiles")}
          action={{ label: t("uploadFiles"), href: filesHref }}
        />
      )}
    </SectionCard>
  );
}
