"use client";

import { SidebarFooter, useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { NavUser } from "./NavUser";

/**
 * Bottom of the sidebar: the account menu. Shared by the main and the settings
 * sidebar so the two stay identical.
 */
export function AppSidebarFooter() {
  const { open } = useSidebar();

  return (
    <SidebarFooter
      className={cn(
        "overflow-hidden border-t border-sidebar-border/60",
        !open && "items-center"
      )}
    >
      <NavUser />
    </SidebarFooter>
  );
}
