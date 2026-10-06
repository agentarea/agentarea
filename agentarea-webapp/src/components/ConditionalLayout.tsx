"use client";

import { Suspense } from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useTranslations } from "next-intl";
import AuthGuard from "@/components/auth/AuthGuard";
import InvitationDialog from "@/components/InvitationDialog/InvitationDialog";
import { AppSidebarContent } from "@/components/MainLayout/components/AppSidebar";
import QuickTaskDialog from "@/components/QuickTask/QuickTaskDialog";
import { SettingsSidebarContent } from "@/components/SettingsLayout/SettingsSidebar";
import { Sidebar, SidebarProvider, SidebarRail } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { navData } from "@/lib/nav-data";
import {
  stripWorkspacePrefix,
  workspaceSection,
  workspaceSlugFromPath,
} from "@/lib/workspace-routes";
import type { Workspace } from "@/lib/workspaces";

interface ConditionalLayoutProps {
  children: React.ReactNode;
  sidebarDefaultOpen?: boolean;
  workspaces: Workspace[];
}

// Everything that used to live under /admin now sits beneath /settings, so the
// one prefix covers it.
const SETTINGS_ROUTES = ["/settings"];

// The (focus) route group: pages that stand alone, opened from a link sent to a chat.
const FOCUS_ROUTES = ["/connect"];

function SkipToContentLink() {
  const t = useTranslations("Common");

  return (
    <a
      href="#workspace-main"
      className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-background focus:px-4 focus:py-3 focus:text-foreground focus:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      {t("skipToContent")}
    </a>
  );
}

export default function ConditionalLayout({
  children,
  sidebarDefaultOpen,
  workspaces,
}: ConditionalLayoutProps) {
  const shouldReduceMotion = useReducedMotion();
  const pathname = usePathname();

  // The layout shell is chosen purely from the route, never from auth state.
  // This keeps SidebarProvider (and the sidebar's open/collapsed state) mounted
  // across auth re-renders; auth only gates the content area below via
  // <AuthGuard>. Previously the shell was conditional on useAuth + a hardcoded
  // route list, so a flapping session (or a route missing from the list) could
  // unmount the provider and silently reset/disable the sidebar. Only
  // `/w/{slug}` pages get it: outside a workspace its links lead nowhere.
  const useNoLayout =
    workspaceSlugFromPath(pathname) === null ||
    FOCUS_ROUTES.includes(workspaceSection(pathname));

  if (useNoLayout) {
    return <>{children}</>;
  }

  const isSettings = SETTINGS_ROUTES.some((route) =>
    stripWorkspacePrefix(pathname).startsWith(route)
  );

  return (
    <SidebarProvider defaultOpen={sidebarDefaultOpen}>
      <SkipToContentLink />
      <div className="flex h-screen w-screen flex-row overflow-hidden bg-layoutBackground py-2 pr-2 pl-2 md:pl-0">
        <Sidebar collapsible="icon">
          <div className="relative h-full w-full overflow-hidden">
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.div
                key={isSettings ? "settings-sidebar" : "main-sidebar"}
                initial={{ x: -10, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: -10, opacity: 0 }}
                transition={
                  shouldReduceMotion
                    ? { duration: 0 }
                    : {
                        type: "spring",
                        stiffness: 260,
                        damping: 30,
                        mass: 1,
                      }
                }
                className="absolute inset-0 flex flex-col h-full w-full"
              >
                {isSettings ? (
                  <SettingsSidebarContent />
                ) : (
                  <AppSidebarContent data={navData} workspaces={workspaces} />
                )}
              </motion.div>
            </AnimatePresence>
          </div>
          {/* Rail lives outside the overflow-hidden animated wrapper so its
              -right-4 toggle strip is not clipped and stays clickable. */}
          <SidebarRail />
        </Sidebar>
        <main
          id="workspace-main"
          tabIndex={-1}
          className="flex-1 rounded-sm overflow-hidden max-h-screen bg-white dark:bg-zinc-800 h-full border border-sidebar-border relative"
        >
          <AuthGuard>{children}</AuthGuard>
        </main>
      </div>
      <ThemeToggle className="fixed bottom-2 right-2 z-50" />
      <QuickTaskDialog />
      <Suspense fallback={null}>
        <InvitationDialog />
      </Suspense>
    </SidebarProvider>
  );
}
