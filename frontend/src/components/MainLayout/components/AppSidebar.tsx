"use client"

import * as React from "react"
import Link from "next/link"
import LogoIcon from "./LogoIcon"
import { NavMain } from './NavMain'
// import { NavProjects } from './NavProjects'
import { NavUser } from './NavUser'
import { TeamSwitcher } from './TeamSwitcher'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
} from '@/components/ui/sidebar'

// This is sample data.

//   projects: [
//     {
//       name: "Design Engineering",
//       url: "#",
//       icon: Frame,
//     },
//     {
//       name: "Sales & Marketing",
//       url: "#",
//       icon: PieChart,
//     },
//     {
//       name: "Travel",
//       url: "#",
//       icon: Map,
//     },
//   ],
// }

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar> & { data: any }) {
  return (
    <Sidebar collapsible="icon" {...props} className="bg-white dark:bg-zinc-800">
      <SidebarHeader className="flex items-start justify-start overflow-hidden">
          <LogoIcon className="h-[32px] mt-2" />
      </SidebarHeader>
      {/* <SidebarHeader>
        <TeamSwitcher teams={props.data.teams} />
      </SidebarHeader> */}
      <SidebarContent>
        <NavMain items={props.data.navMain} />
        {/* <NavProjects projects={data.projects} /> */}
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={props.data.user} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}