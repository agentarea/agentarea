"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { getPendingApprovalCountAction } from "@/components/Approvals/actions";
import Link from "@/components/WorkspaceLink";
import { useWorkspacePathname } from "@/hooks/useWorkspaceNavigation";
import { Inbox, SquarePen } from "lucide-react";
import {
  SidebarGroup,
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
import { NavHelp } from "./NavHelp";
import { NavMain, navItemClassName } from "./NavMain";
import { NavSearch } from "./NavSearch";
import { SidebarNavScroll } from "./SidebarNavScroll";
import { TeamSwitcher } from "./TeamSwitcher";

// New task and Inbox are actions, not places: framed like the search field
// below them so they do not read as two more nav rows.
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
  const homeActive = pathname === "/workplace";
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
            className={cn(
              navItemClassName,
              headerButtonClassName,
              "min-w-0 flex-1 font-medium [&>svg]:text-primary dark:[&>svg]:text-primary"
            )}
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
                  <Kbd keys={["⌘", "J"]} />
                </>
              )}
            </Link>
          </SidebarMenuButton>
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
        <NavSearch sections={data.navSections} />
      </SidebarHeader>
      <SidebarNavScroll>
        <NavMain sections={data.navSections} />
      </SidebarNavScroll>
      <SidebarGroup className="py-1">
        <NavHelp />
      </SidebarGroup>
      <AppSidebarFooter />
    </>
  );
}
