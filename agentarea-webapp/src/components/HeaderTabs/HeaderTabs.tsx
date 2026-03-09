"use client";

import { useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { setCookie } from "@/utils/cookies";
import Tab from "./components/Tab";

export interface TabItem {
  value: string;
  label: string;
  icon?: React.ReactNode;
}

export interface HeaderTabsProps {
  tabs: TabItem[];
  paramName?: string;
  defaultTab?: string;
  currentTab?: string;
}

export default function HeaderTabs({
  tabs,
  paramName = "tab",
  defaultTab,
  currentTab,
}: HeaderTabsProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // Generate unique cookie key based on current path
  const cookieKey = useMemo(() => {
    const cleanPath = pathname.replace(/^\/+/, "").replace(/\//g, "_");
    return `${paramName}_${cleanPath}`;
  }, [pathname, paramName]);

  const urlTab = searchParams.get(paramName);

  // Active tab is derived from URL, passed currentTab, or default
  const activeTab = urlTab || currentTab || defaultTab || tabs[0]?.value;

  const handleTabChange = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set(paramName, value);
    const newUrl = `${pathname}?${params.toString()}`;

    // Save tab to cookies with unique key
    setCookie(cookieKey, value);

    router.push(newUrl, { scroll: false });
  };

  return (
    <div className="flex items-center gap-3">
      {tabs.map((tab) => (
        <Tab
          key={tab.value}
          isActive={activeTab === tab.value}
          onClick={() => handleTabChange(tab.value)}
        >
          {tab.icon}
          {tab.label}
        </Tab>
      ))}
    </div>
  );
}
