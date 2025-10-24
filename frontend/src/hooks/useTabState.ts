import { useCallback, useEffect, useMemo, useState } from "react";
import { useCookie } from "./useCookie";

// Универсальный хук для работы с табами
export function useTabState(pathname: string, urlTab: string | null) {
  const cookieKey = useMemo(() => {
    const cleanPath = pathname.replace(/^\/+/, "").replace(/\//g, "_");
    return `tab_${cleanPath}`;
  }, [pathname]);

  const [savedTab, setSavedTab] = useCookie(cookieKey, "grid");
  const [isTabLoaded, setIsTabLoaded] = useState(false);

  useEffect(() => {
    setIsTabLoaded(true);
  }, []);

  const currentTab = urlTab || savedTab || "grid";

  const updateTab = useCallback(
    (tab: string) => {
      if (tab === "grid" || tab === "table") {
        setSavedTab(tab);
      }
    },
    [setSavedTab]
  );

  return {
    currentTab,
    isTabLoaded,
    updateTab,
  };
}
