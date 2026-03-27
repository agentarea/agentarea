"use client";

import { Skill, SkillFile } from "@/lib/api";
import { InfoPanelBody, InfoPanelShell } from "@/components/InfoPanel";
import SkillInfoHeader from "./components/SkillInfoHeader";
import SkillDetails from "./components/SkillDetails";
import SkillFiles from "./components/SkillFiles";

interface SkillPanelProps {
  skill: Skill;
  files?: SkillFile[];
  onFileSelect?: (path: string) => void;
  selectedFile?: string | null;
}

export default function SkillPanel({
  skill,
  files = [],
  onFileSelect,
  selectedFile,
}: SkillPanelProps) {
  return (
    <InfoPanelShell>
      <SkillInfoHeader skill={skill} />
      <InfoPanelBody>
        <SkillDetails skill={skill} />

        <SkillFiles
          files={files}
          onFileSelect={onFileSelect}
          selectedFile={selectedFile}
        />
      </InfoPanelBody>
    </InfoPanelShell>
  );
}
