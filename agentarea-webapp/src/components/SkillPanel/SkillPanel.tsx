"use client";

import { Skill, SkillFile } from "@/lib/browser-api";
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
    <div className="h-full overflow-auto border-l border-zinc-200 dark:border-zinc-700">
      <div className="min-h-full bg-white dark:bg-zinc-800">
        {/* Header */}
        <SkillInfoHeader skill={skill} />

        {/* Content sections */}
        <div className="space-y-4 px-3.5 py-3 text-xs">
          <SkillDetails skill={skill} />

          <SkillFiles
            files={files}
            onFileSelect={onFileSelect}
            selectedFile={selectedFile}
          />
        </div>
      </div>
    </div>
  );
}
