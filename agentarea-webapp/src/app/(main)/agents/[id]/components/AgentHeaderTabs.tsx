"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CreditCard,
  List,
  MessagesSquare,
  Settings,
  // Wallet,
} from "lucide-react";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "new-task", icon: MessagesSquare, labelKey: "createTask" },
  { key: "tasks", icon: List, labelKey: "currentTasks" },
  { key: "payments", icon: CreditCard, labelKey: "payments" },
  // { key: "wallet", icon: Wallet, labelKey: "wallet" },
  { key: "settings", icon: Settings, labelKey: "settings" },
];

export default function AgentHeaderTabs({ agentId }: { agentId: string }) {
  const t = useTranslations("AgentsPage");
  const pathname = usePathname();
  const containerRef = useRef<HTMLDivElement>(null);
  const linkRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [indicatorStyle, setIndicatorStyle] = useState({ left: 0, width: 0 });

  useLayoutEffect(() => {
    const activeIndex = TABS.findIndex(
      (tab) => pathname === `/agents/${agentId}/${tab.key}`
    );
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
  }, [pathname, agentId]);

  return (
    <div
      ref={containerRef}
      className="inline-flex items-center gap-3 py-0 relative"
    >
      {TABS.map((tab, index) => {
        const href = `/agents/${agentId}/${tab.key}`;
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
