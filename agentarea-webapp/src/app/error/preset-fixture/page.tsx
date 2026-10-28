"use client";

import { useState } from "react";
import type { AgentPresetResponse } from "@/api/client/types.gen";
import PresetPicker from "@/app/w/[workspace]/(main)/agents/create/components/PresetPicker";

const PRESETS = [
  { id: "777180a3-f36c-4d75-8798-07c9bcdbcfb7", name: "Research Assistant", description: "Researches topics and produces cited summaries.", instruction: "x", tools: [{}, {}], skills: [{ id: "s", name: "docx" }], triggers: [{}], unavailable_skills: [] },
  { id: "204e0b89-da5f-4d7d-9af2-58c94807947c", name: "Code Reviewer", description: "Reviews diffs for bugs, security issues, and clarity.", instruction: "x", tools: [{}, {}], skills: [], triggers: [], unavailable_skills: [] },
  { id: "1548f615-1cda-48b5-82f7-4bf234c4c01c", name: "Content Writer", description: "Drafts blog posts and marketing copy from a brief.", instruction: "x", tools: [{}, {}], skills: [{ id: "s", name: "docx" }], triggers: [{}], unavailable_skills: [] },
] as unknown as AgentPresetResponse[];

export default function PresetFixture() {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PresetPicker presets={PRESETS} selectedId={selected} onSelect={(p) => setSelected(p?.id ?? null)} />
    </div>
  );
}
