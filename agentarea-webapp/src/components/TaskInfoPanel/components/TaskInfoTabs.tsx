import { useTranslations } from "next-intl";
import { AnimatedTabs } from "@/components/ui/animated-tabs";

interface TaskInfoTabsProps {
  activeTab: "overview" | "model";
  setActiveTab: (tab: "overview" | "model") => void;
}

export default function TaskInfoTabs({ activeTab, setActiveTab }: TaskInfoTabsProps) {
  const t = useTranslations("TaskInfoPanel");
  
  const tabs = [
    { value: "overview", label: t("overview") },
    { value: "model", label: t("modelInfo") },
  ];

  return (
    <div className="px-3 pt-2.5 pb-1.5">
      <AnimatedTabs
        tabs={tabs}
        activeTab={activeTab}
        onChange={(val) => setActiveTab(val as "overview" | "model")}
        className="p-0.5"
      />
    </div>
  );
}
