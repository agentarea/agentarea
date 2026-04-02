"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  Brain,
  LayoutDashboard,
  Package,
} from "lucide-react";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "", icon: LayoutDashboard, labelKey: "overview" },
  { key: "events", icon: Activity, labelKey: "events" },
  { key: "artifacts", icon: Package, labelKey: "artifacts" },
  { key: "memory", icon: Brain, labelKey: "memory" },
  { key: "metrics", icon: BarChart3, labelKey: "metrics" },
];

export default function TaskSubheader({ taskId }: { taskId: string }) {
  const t = useTranslations("TasksPage.tabs");
  const pathname = usePathname();
  const containerRef = useRef<HTMLDivElement>(null);
  const linkRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [indicatorStyle, setIndicatorStyle] = useState({ left: 0, width: 0 });

  useLayoutEffect(() => {
    const activeIndex = TABS.findIndex((tab) => {
      const href = tab.key ? `/tasks/${taskId}/${tab.key}` : `/tasks/${taskId}`;
      return pathname === href;
    });
    if (activeIndex !== -1 && linkRefs.current[activeIndex]) {
      const activeLink = linkRefs.current[activeIndex]!;
      const container = containerRef.current;
      if (container) {
        const containerRect = container.getBoundingClientRect();
        const linkRect = activeLink.getBoundingClientRect();
        setIndicatorStyle({
          left: linkRect.left - containerRect.left,
          width: linkRect.width,
        });
      }
    }
  }, [pathname, taskId]);

  return (
    <div
      ref={containerRef}
      className="inline-flex items-center gap-3 py-0 relative"
    >
      {TABS.map((tab, index) => {
        const href = tab.key
          ? `/tasks/${taskId}/${tab.key}`
          : `/tasks/${taskId}`;
        const isActive = pathname === href;
        const Icon = tab.icon;

        return (
          <Link
            key={tab.key}
            href={href}
            ref={(el) => {
              linkRefs.current[index] = el;
            }}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex items-center gap-1 px-1 py-2.5 text-xs",
              isActive
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="h-4 w-4" />
            {t(tab.labelKey)}
          </Link>
        );
      })}
      <div
        className="absolute -bottom-[1.2px] h-[1.5px] bg-foreground transition-all duration-300 ease-out rounded-full"
        style={{
          left: indicatorStyle.left,
          width: indicatorStyle.width,
        }}
      />
    </div>
  );
}
