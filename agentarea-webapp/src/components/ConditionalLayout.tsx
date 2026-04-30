"use client";

import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import AuthGuard from "@/components/auth/AuthGuard";
import { AppSidebarContent } from "@/components/MainLayout/components/AppSidebar";
import QuickTaskDialog from "@/components/QuickTask/QuickTaskDialog";
import { SettingsSidebarContent } from "@/components/SettingsLayout/SettingsSidebar";
import { Sidebar, SidebarProvider } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { useAuth } from "@/hooks/useAuth";
import { navData } from "@/lib/nav-data";

interface ConditionalLayoutProps {
  children: React.ReactNode;
  sidebarDefaultOpen?: boolean;
}

const NO_LAYOUT_ROUTES = ["/auth", "/error", "/404", "/500"];
const PROTECTED_ROUTES = [
  "/workplace",
  "/agents",
  "/tasks",
  "/mcp-servers",
  "/settings",
  "/admin",
  "/skills",
  "/triggers",
  "/inbox",
  "/projects",
  "/network",
];

const SETTINGS_ROUTES = ["/settings", "/admin/api-keys", "/admin/workspace"];

export default function ConditionalLayout({
  children,
  sidebarDefaultOpen,
}: ConditionalLayoutProps) {
  const pathname = usePathname();
  const { isSignedIn, isLoaded } = useAuth();

  // Always skip layout for auth pages and root page
  const shouldUseNoLayout =
    NO_LAYOUT_ROUTES.some((route) => pathname.startsWith(route)) ||
    pathname === "/";

  if (shouldUseNoLayout) {
    return <>{children}</>;
  }

  // For unknown routes: only use main layout if user is authenticated
  const isKnownRoute = PROTECTED_ROUTES.some((route) =>
    pathname.startsWith(route)
  );

  if (!isKnownRoute && isLoaded && !isSignedIn) {
    // Unknown route + unauthenticated = no layout (clean 404)
    return <>{children}</>;
  }

  const isSettings = SETTINGS_ROUTES.some((route) =>
    pathname.startsWith(route)
  );

  return (
    <AuthGuard>
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
                    <AppSidebarContent data={navData} />
                  )}
                </motion.div>
              </AnimatePresence>
            </div>
          </Sidebar>
          <main className="flex-1 rounded-sm overflow-hidden max-h-screen bg-white dark:bg-zinc-800 h-full border border-sidebar-border relative">
            {children}
          </main>
        </div>
        <ThemeToggle className="fixed bottom-2 right-2 z-50" />
        <QuickTaskDialog />
      </SidebarProvider>
    </AuthGuard>
  );
}
