"use client"

import * as React from "react";
// import LogoIcon from "./LogoIcon";
import { NavMain } from './NavMain';
import { NavUser } from './NavUser';
import { TeamSwitcher } from './TeamSwitcher';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarTrigger,
  SidebarRail,
} from '@/components/ui/sidebar';
import { useSidebar } from '@/components/ui/sidebar';
import { cn } from '@/lib/utils';

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar> & { data: any }) {
  const { open } = useSidebar();
  return (
    <Sidebar collapsible="icon" {...props} className="bg-white dark:bg-zinc-800">
      {/* <SidebarHeader className="flex items-center justify-between overflow-hidden flex-row">
          <LogoIcon className="h-[32px] mt-2" />
          <SidebarTrigger/>
      </SidebarHeader> */}
      <SidebarHeader>
        <TeamSwitcher teams={props.data.workspaces} />
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={props.data.navMain} />
      </SidebarContent>
      <SidebarFooter 
        className={cn(
            `flex items-center justify-between overflow-hidden flex-row`, 
            open ? 'flex-row' : 'flex-col-reverse ')}
        >
        <NavUser user={props.data.user} />
        <SidebarTrigger className="hidden md:flex" />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}