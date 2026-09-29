"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import Link from "@/components/WorkspaceLink";
import { useWorkspacePathname } from "@/hooks/useWorkspaceNavigation";
import { Inbox, SquarePen } from "lucide-react";
import {
  SidebarHeader,
  SidebarMenuButton,
  useSidebar,
} from "@/components/ui/sidebar";
import { Kbd } from "@/components/ui/kbd";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Workspace } from "@/lib/workspaces";
import { AppSidebarFooter } from "./AppSidebarFooter";
import { NavMain, navItemClassName } from "./NavMain";
import { SidebarNavScroll } from "./SidebarNavScroll";
import { TeamSwitcher } from "./TeamSwitcher";

interface AppSidebarData {
  navSections: React.ComponentProps<typeof NavMain>["sections"];
}

export function AppSidebarContent({
  data,
  workspaces,
}: {
  data: AppSidebarData;
  workspaces: Workspace[];
}) {
  const { open } = useSidebar();
  const t = useTranslations("Sidebar");
  const pathname = useWorkspacePathname();
  const inboxActive = pathname === "/inbox" || pathname.startsWith("/inbox/");
  const homeActive = pathname === "/workplace";

  return (
    <>
      <SidebarHeader>
        <TeamSwitcher workspaces={workspaces} />
        <div className={cn("flex items-center gap-1", !open && "flex-col")}>
          {/* Like the nav items, the tooltip only shows while the sidebar is
              collapsed; expanded, the label is already visible. */}
          <SidebarMenuButton
            asChild
            isActive={homeActive}
            tooltip={{
              // Layout goes on an inner span: a display class on the content
              // itself would override the `hidden` that keeps it off while
              // the sidebar is expanded.
              children: (
                <span className="flex items-center gap-1.5">
                  {t("newTask")}
                  <Kbd keys={["⌘", "J"]} variant="inverse" />
                </span>
              ),
            }}
            className={cn(navItemClassName, "group/new-task min-w-0 flex-1")}
          >
            <Link
              href="/workplace"
              aria-current={homeActive ? "page" : undefined}
            >
              <SquarePen />
              {open && (
                <>
                  <span className="min-w-0 flex-1 truncate">
                    {t("newTask")}
                  </span>
                  {/* Hidden at rest so it does not read as a second control
                      competing with the label. */}
                  <Kbd
                    keys={["⌘", "J"]}
                    className="opacity-0 transition-opacity duration-200 group-hover/new-task:opacity-100 group-focus-visible/new-task:opacity-100"
                  />
                </>
              )}
            </Link>
          </SidebarMenuButton>
          <Tooltip>
            <TooltipTrigger asChild>
              <SidebarMenuButton
                asChild
                isActive={inboxActive}
                className={cn(navItemClassName, "w-8 shrink-0")}
              >
                <Link
                  href="/inbox"
                  aria-label={t("inbox")}
                  aria-current={inboxActive ? "page" : undefined}
                >
                  <Inbox />
                </Link>
              </SidebarMenuButton>
            </TooltipTrigger>
            <TooltipContent side="right">{t("inbox")}</TooltipContent>
          </Tooltip>
        </div>
      </SidebarHeader>
      <SidebarNavScroll>
        <NavMain sections={data.navSections} />
      </SidebarNavScroll>
      <AppSidebarFooter />
    </>
  );
}
