"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

export default function AgentHeaderTabs() {
  const t = useTranslations("Agent");
  const searchParams = useSearchParams();
  const pathname = usePathname();

  const initialTab = useMemo(() => {
    const tab = searchParams.get("tab");
    return tab === "all" ? "all" : "new";
  }, [searchParams]);

  const [activeTab, setActiveTab] = useState<string>(initialTab);

  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get("tab");
      setActiveTab(tab === "all" ? "all" : "new");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", value);
    const newUrl = `${pathname}?${params.toString()}`;
    window.history.pushState({}, "", newUrl);
  };

  return (
    <Tabs value={activeTab} onValueChange={handleTabChange}>
      <TabsList>
        <TabsTrigger value="new" className="px-[10px] sm:px-[20px]">
          {t("createTask")}
        </TabsTrigger>
        <TabsTrigger value="all" className="px-[10px] sm:px-[20px]">
          {t("currentTasks")}
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
}


