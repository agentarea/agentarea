"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { Inbox } from "lucide-react";
import { getPendingApprovalCountAction } from "@/components/Approvals/actions";
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

// Inbox sits beside the search field and is framed like it, so it does not
// read as one more nav row.
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
  const inboxActive = pathname === "/inbox" || pathname.startsWith("/inbox/");
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
  const inboxLabel =
    pendingApprovals > 0
      ? t("inboxPending", { count: pendingApprovals })
      : t("inbox");

  return (
    <>
      <SidebarHeader>
        <TeamSwitcher workspaces={workspaces} />
        <div className={cn("flex items-center gap-1", !open && "flex-col")}>
          <div className="min-w-0 flex-1">
            <NavSearch sections={data.navSections} />
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <SidebarMenuButton
                asChild
                isActive={inboxActive}
                // The count badge hangs past the corner; the menu button's
                // base overflow-hidden would clip it.
                className={cn(
                  navItemClassName,
                  headerButtonClassName,
                  "relative w-8 shrink-0 justify-center overflow-visible"
                )}
              >
                <Link
                  href="/inbox"
                  aria-label={inboxLabel}
                  aria-current={inboxActive ? "page" : undefined}
                >
                  <Inbox />
                  {pendingApprovals > 0 && (
                    <span
                      aria-hidden
                      className="pointer-events-none absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-[color:var(--status-attention)] px-1 text-[10px] font-semibold leading-none text-white tabular-nums"
                    >
                      {pendingApprovals > 99 ? "99+" : pendingApprovals}
                    </span>
                  )}
                </Link>
              </SidebarMenuButton>
            </TooltipTrigger>
            <TooltipContent side="right">{inboxLabel}</TooltipContent>
          </Tooltip>
        </div>
      </SidebarHeader>
      <SidebarNavScroll>
        <NavMain sections={data.navSections} />
      </SidebarNavScroll>
      <SidebarGroup className="gap-0 py-1 before:mx-2 before:mb-1 before:block before:border-t before:border-sidebar-border">
        <SidebarBalance />
        <NavHelp />
      </SidebarGroup>
      <AppSidebarFooter />
    </>
  );
}
