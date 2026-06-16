import { useTranslations } from "next-intl";
import { FileChip } from "@/components/Chat/utils/fileIcon";
import Section from "./Section";

interface FilesProps {
  files?: string[];
}

/** Files the agent touched during the run (read/written/produced). */
export default function Files({ files }: FilesProps) {
  const t = useTranslations("TaskInfoPanel");

  if (!files || files.length === 0) {
    return null;
  }

  return (
    <Section title={t("files")} contentClassName="flex flex-wrap gap-1.5 text-xs">
      {files.map((file) => (
        <span
          key={file}
          className="inline-flex items-center rounded-md bg-muted/60 px-2 py-1"
        >
          <FileChip name={file} />
        </span>
      ))}
    </Section>
  );
}
