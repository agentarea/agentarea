"use client";

import { useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { LayoutGrid, List } from "lucide-react";
import { cn } from "@/lib/utils";
import { setCookie } from "@/utils/cookies";

export interface TabItem {
  value: string;
  /** Accessible label / tooltip — the control is icon-only. */
  label: string;
  /** Optional override; by default the icon is derived from `value`. */
  icon?: React.ReactNode;
}

/**
 * Canonical view-toggle icons, keyed by tab value. Every grid/table (or
 * list/grid) switcher uses these so the control looks identical everywhere —
 * callers don't pass icons.
 */
const TAB_ICONS: Record<string, React.ReactNode> = {
  grid: <LayoutGrid className="h-4 w-4" />,
  list: <List className="h-4 w-4" />,
  table: <List className="h-4 w-4" />,
};

export interface HeaderTabsProps {
  tabs: TabItem[];
  paramName?: string;
  defaultTab?: string;
  currentTab?: string;
  className?: string;
  /**
   * Controlled mode: pass `value` + `onChange` to drive the toggle from your
   * own state (used by the Skills page). Omit both for the default URL-param
   * + per-path cookie behaviour.
   */
  value?: string;
  onChange?: (value: string) => void;
}

/**
 * Compact, Linear-style segmented icon switcher used everywhere a grid/table
 * (or list/grid) view toggle is shown.
 */
export default function HeaderTabs({
  tabs,
  paramName = "tab",
  defaultTab,
  currentTab,
  className,
  value,
  onChange,
}: HeaderTabsProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // Unique cookie key based on current path.
  const cookieKey = useMemo(() => {
    const cleanPath = pathname.replace(/^\/+/, "").replace(/\//g, "_");
    return `${paramName}_${cleanPath}`;
  }, [pathname, paramName]);

  const controlled = value !== undefined && onChange !== undefined;

  const activeTab = controlled
    ? value
    : searchParams.get(paramName) || currentTab || defaultTab || tabs[0]?.value;

  const handleChange = (next: string) => {
    if (controlled) {
      onChange?.(next);
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    params.set(paramName, next);
    setCookie(cookieKey, next);
    router.push(`${pathname}?${params.toString()}`, { scroll: false });
  };

  return (
    <div
      className={cn("inline-flex rounded-md bg-muted p-0.5", className)}
      role="group"
    >
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          title={tab.label}
          aria-label={tab.label}
          aria-pressed={activeTab === tab.value}
          onClick={() => handleChange(tab.value)}
          className={cn(
            "grid h-6 w-[30px] place-items-center rounded-[5px] transition-colors",
            activeTab === tab.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {TAB_ICONS[tab.value] ?? tab.icon}
        </button>
      ))}
    </div>
  );
}
