"use client";

import * as React from "react";
import Image from "next/image";
import { ChevronsUpDown, Plus } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";

export function TeamSwitcher({
  teams,
}: {
  teams: {
    name: string;
    logo: React.ElementType;
    plan: string;
    logoFile?: string;
  }[];
}) {
  const { isMobile } = useSidebar();
  const [activeTeam, setActiveTeam] = React.useState(teams[0]);

  if (!activeTeam) {
    return null;
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground transition-all duration-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              <div className="flex aspect-square size-8 items-center justify-center bg-transparent text-sidebar-primary-foreground">
                {activeTeam.logoFile ? (
                  <Image
                    src={activeTeam.logoFile}
                    alt={activeTeam.name}
                    width={32}
                    height={32}
                    className=""
                  />
                ) : (
                  <activeTeam.logo className="size-4 text-zinc-900 dark:text-zinc-100" />
                )}
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                  {activeTeam.name}
                </span>
                <span className="truncate text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
                  {activeTeam.plan}
                </span>
              </div>
              <ChevronsUpDown className="ml-auto text-zinc-400" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            align="start"
            side={isMobile ? "bottom" : "right"}
            sideOffset={4}
          >
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              Workspaces
            </DropdownMenuLabel>
            {teams.map((team, index) => (
              <DropdownMenuItem
                key={team.name}
                onClick={() => setActiveTeam(team)}
                className="gap-2 p-2"
              >
                <div className="flex size-6 items-center justify-center rounded-md border">
                  {team.logoFile ? (
                    <Image
                      src={team.logoFile}
                      alt={team.name}
                      width={32}
                      height={32}
                    />
                  ) : (
                    <team.logo className="size-3.5 shrink-0" />
                  )}
                </div>
                {team.name}
                <DropdownMenuShortcut>⌘{index + 1}</DropdownMenuShortcut>
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem className="gap-2 p-2 cursor-pointer">
              <div className="flex size-6 items-center justify-center rounded-md border bg-primary/10">
                <Plus className="size-4 text-primary" />
              </div>
              <span className="text-sm font-medium">Add Workspace</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
