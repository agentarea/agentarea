"use client";

import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import AuthGuard from "@/components/auth/AuthGuard";
import { AppSidebarContent } from "@/components/MainLayout/components/AppSidebar";
import QuickTaskDialog from "@/components/QuickTask/QuickTaskDialog";
import { SettingsSidebarContent } from "@/components/SettingsLayout/SettingsSidebar";
import { Sidebar, SidebarProvider, SidebarRail } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { navData } from "@/lib/nav-data";
import type { Workspace } from "@/lib/workspaces";

interface ConditionalLayoutProps {
  children: React.ReactNode;
  sidebarDefaultOpen?: boolean;
  workspaces: Workspace[];
  activeWorkspaceSlug: string | null;
}

// Routes that render their own full-page chrome (landing, auth, error) and
// therefore must not be wrapped in the app shell / sidebar.
const NO_LAYOUT_ROUTES = ["/auth", "/error", "/404", "/500"];

const SETTINGS_ROUTES = ["/settings", "/admin/api-keys", "/admin/workspace"];

export default function ConditionalLayout({
  children,
  sidebarDefaultOpen,
  workspaces,
  activeWorkspaceSlug,
}: ConditionalLayoutProps) {
  const pathname = usePathname();

  // The layout shell is chosen purely from the route, never from auth state.
  // This keeps SidebarProvider (and the sidebar's open/collapsed state) mounted
  // across auth re-renders; auth only gates the content area below via
  // <AuthGuard>. Previously the shell was conditional on useAuth + a hardcoded
  // route list, so a flapping session (or a route missing from the list) could
  // unmount the provider and silently reset/disable the sidebar.
  const useNoLayout =
    pathname === "/" ||
    NO_LAYOUT_ROUTES.some((route) => pathname.startsWith(route));

  if (useNoLayout) {
    return <>{children}</>;
  }

  const isSettings = SETTINGS_ROUTES.some((route) =>
    pathname.startsWith(route)
  );

  return (
    <SidebarProvider defaultOpen={sidebarDefaultOpen}>
      <div className="flex h-screen w-screen flex-row overflow-hidden bg-layoutBackground py-2 pr-2 pl-2 md:pl-0">
        <Sidebar collapsible="icon">
          <div className="relative h-full w-full overflow-hidden">
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.div
                key={isSettings ? "settings-sidebar" : "main-sidebar"}
                initial={{ x: -10, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: -10, opacity: 0 }}
                transition={{
                  type: "spring",
                  stiffness: 260,
                  damping: 30,
                  mass: 1,
                }}
                className="absolute inset-0 flex flex-col h-full w-full"
              >
                {isSettings ? (
                  <SettingsSidebarContent />
                ) : (
                  <AppSidebarContent
                    data={navData}
                    workspaces={workspaces}
                    activeWorkspaceSlug={activeWorkspaceSlug}
                  />
                )}
              </motion.div>
            </AnimatePresence>
          </div>
          {/* Rail lives outside the overflow-hidden animated wrapper so its
              -right-4 toggle strip is not clipped and stays clickable. */}
          <SidebarRail />
        </Sidebar>
        <main className="flex-1 rounded-sm overflow-hidden max-h-screen bg-white dark:bg-zinc-800 h-full border border-sidebar-border relative">
          <AuthGuard>{children}</AuthGuard>
        </main>
      </div>
      <ThemeToggle className="fixed bottom-2 right-2 z-50" />
      <QuickTaskDialog />
    </SidebarProvider>
  );
}
