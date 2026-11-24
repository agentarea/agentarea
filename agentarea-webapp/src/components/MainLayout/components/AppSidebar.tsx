"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { SquarePen } from "lucide-react";
import { getPendingApprovalCountAction } from "@/components/Approvals/actions";
import { Kbd } from "@/components/ui/kbd";
import {
  SidebarGroup,
  SidebarHeader,
  SidebarMenuButton,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Link from "@/components/WorkspaceLink";
import { useWorkspacePathname } from "@/hooks/useWorkspaceNavigation";
import { cn } from "@/lib/utils";
import type { Workspace } from "@/lib/workspaces";
import { AppSidebarFooter } from "./AppSidebarFooter";
import { NavHelp } from "./NavHelp";
import { navItemClassName, NavMain } from "./NavMain";
import { NavSearch } from "./NavSearch";
import { SidebarBalance } from "./SidebarBalance";
import { SidebarNavScroll } from "./SidebarNavScroll";
import { TeamSwitcher } from "./TeamSwitcher";

// New task sits beside the search field and is framed like it: an action, not
// one more nav row.
const headerButtonClassName =
  "border border-sidebar-border bg-background shadow-sm hover:bg-zinc-50 dark:bg-zinc-900 dark:hover:bg-zinc-800";

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
  const newTaskActive = pathname === "/workplace";
  const [pendingApprovals, setPendingApprovals] = React.useState(0);

  // Re-read on every navigation (deciding in the inbox or on a task page
  // changes it) and periodically, so new escalations surface while idle.
  React.useEffect(() => {
    let cancelled = false;
    const load = () =>
      getPendingApprovalCountAction()
        .then((result) => {
          if (cancelled) return;
          if (result.error) {
            console.error("Failed to count pending approvals", result.error);
            return;
          }
          setPendingApprovals(result.data ?? 0);
        })
        .catch((error: unknown) => {
          console.error("Failed to count pending approvals", error);
        });
    void load();
    const interval = window.setInterval(load, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [pathname]);

  return (
    <>
      <SidebarHeader>
        <TeamSwitcher workspaces={workspaces} />
        <div className={cn("flex items-center gap-1", !open && "flex-col")}>
          <div className="min-w-0 flex-1">
            <NavSearch sections={data.navSections} />
          </div>
          {/* Icon only, so its name shows on hover whether the sidebar is
              expanded or collapsed. */}
          <Tooltip>
            <TooltipTrigger asChild>
              <SidebarMenuButton
                asChild
                isActive={newTaskActive}
                className={cn(
                  navItemClassName,
                  headerButtonClassName,
                  "w-8 shrink-0 justify-center [&>svg]:text-primary dark:[&>svg]:text-primary"
                )}
              >
                <Link
                  href="/workplace"
                  aria-label={t("newTask")}
                  aria-current={newTaskActive ? "page" : undefined}
                >
                  <SquarePen />
                </Link>
              </SidebarMenuButton>
            </TooltipTrigger>
            <TooltipContent
              side={open ? "bottom" : "right"}
              className="flex items-center gap-1.5"
            >
              {t("newTask")}
              <Kbd keys={["⌘", "J"]} variant="inverse" />
            </TooltipContent>
          </Tooltip>
        </div>
      </SidebarHeader>
      <SidebarNavScroll>
        <NavMain
          sections={data.navSections}
          counts={{ "/inbox": pendingApprovals }}
        />
      </SidebarNavScroll>
      <SidebarGroup className="gap-0 py-1 before:mx-2 before:mb-1 before:block before:border-t before:border-sidebar-border">
        <SidebarBalance />
        <NavHelp />
      </SidebarGroup>
      <AppSidebarFooter />
    </>
  );
}
