"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { getCookie, setCookie } from "@/utils/cookies";
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
}

export default function HeaderTabs({
  tabs,
  paramName = "tab",
  defaultTab,
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

  // Use state to avoid hydration mismatch - start with URL or default
  const [activeTab, setActiveTab] = useState<string>(
    urlTab || defaultTab || tabs[0]?.value
  );

  // Track if we've synced URL with cookie
  const [hasUrlSynced, setHasUrlSynced] = useState(false);

  // Sync with cookie after hydration (client-only)
  useEffect(() => {
    const cookieTab = getCookie(cookieKey);

    if (!hasUrlSynced && !urlTab && cookieTab) {
      const params = new URLSearchParams(searchParams.toString());
      params.set(paramName, cookieTab);
      const newUrl = `${pathname}?${params.toString()}`;
      // Use replace to avoid adding to history
      router.replace(newUrl, { scroll: false });
      setActiveTab(cookieTab);
      setHasUrlSynced(true);
    } else if (!hasUrlSynced) {
      setHasUrlSynced(true);
    }
  }, [
    hasUrlSynced,
    urlTab,
    cookieKey,
    searchParams,
    paramName,
    pathname,
    router,
  ]);

  // Update active tab when URL changes
  useEffect(() => {
    if (urlTab) {
      setActiveTab(urlTab);
    }
  }, [urlTab]);

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
