"use client";

import { useTranslations } from "next-intl";
import { AnimatedTabs } from "@/components/ui/animated-tabs";

interface SkillInfoTabsProps {
  activeTab: "details" | "files";
  setActiveTab: (tab: "details" | "files") => void;
}

export default function SkillInfoTabs({ activeTab, setActiveTab }: SkillInfoTabsProps) {
  const tDetail = useTranslations("SkillsPage.detail");
  
  const tabs = [
    { value: "details", label: tDetail("details") },
    { value: "files", label: tDetail("files") },
  ];

  return (
    <div className="px-3 pt-2.5 pb-1.5">
      <AnimatedTabs
        tabs={tabs}
        activeTab={activeTab}
        onChange={(val) => setActiveTab(val as "details" | "files")}
        className="p-0.5"
      />
    </div>
  );
}
