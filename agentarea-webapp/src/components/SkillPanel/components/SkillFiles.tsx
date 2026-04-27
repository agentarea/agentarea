"use client";

import { useTranslations } from "next-intl";
import { SkillFile } from "@/lib/api";
import Section from "@/components/TaskInfoPanel/components/Section";
import { FileTree, type BrowsedFile } from "@/components/files/file-tree";

interface SkillFilesProps {
  files: SkillFile[];
  onFileSelect?: (path: string) => void;
  selectedFile?: string | null;
}

export default function SkillFiles({ files, onFileSelect, selectedFile }: SkillFilesProps) {
  const tDetail = useTranslations("SkillsPage.detail");

  const browsedFiles: BrowsedFile[] = files.map((f) => ({
    path: f.path,
    size: f.size,
  }));

  return (
    <Section title={tDetail("files")} contentClassName="space-y-3 text-xs">
      {browsedFiles.length > 0 ? (
        <FileTree
          files={browsedFiles}
          selectedPath={selectedFile ?? null}
          onSelect={(file) => onFileSelect?.(file.path)}
        />
      ) : (
        <div className="text-muted-foreground text-center py-4">
          {tDetail("emptyFile")}
        </div>
      )}
    </Section>
  );
}
