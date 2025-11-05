"use client";

import * as React from "react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { NavMain } from "./NavMain";
import { NavUser } from "./NavUser";
import { TeamSwitcher } from "./TeamSwitcher";

export function AppSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar> & { data: any }) {
  const { open } = useSidebar();
  return (
    <Sidebar
      collapsible="icon"
      {...props}
      className=""
    >
      <SidebarHeader>
        <TeamSwitcher teams={props.data.workspaces} />
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={props.data.navMain} />
      </SidebarContent>
      <SidebarFooter
        className={cn(
          `flex flex-row items-center justify-between overflow-hidden`,
          open ? "flex-row" : "flex-col-reverse"
        )}
      >
        <NavUser />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
