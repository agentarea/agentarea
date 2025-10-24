"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Tabs } from "@/components/ui/tabs";
import { setCookie } from "@/utils/cookies";

export function TabsWithNavigation({
  activeTab,
  children,
  routeChange,
}: {
  activeTab: string;
  children: React.ReactNode;
  routeChange: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  const handleTabChange = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", value);
    const newUrl = `${routeChange}?${params.toString()}`;

    // Generate unique cookie key based on current path
    const generateCookieKey = (path: string) => {
      const cleanPath = path.replace(/^\/+/, "").replace(/\//g, "_");
      return `tab_${cleanPath}`;
    };

    const cookieKey = generateCookieKey(pathname);

    // Save tab to cookies with unique key
    setCookie(cookieKey, value);

    router.push(newUrl, { scroll: false });
  };

  return (
    <Tabs
      value={activeTab}
      // className="w-full"
      defaultValue="grid"
      onValueChange={handleTabChange}
    >
      {children}
    </Tabs>
  );
}
