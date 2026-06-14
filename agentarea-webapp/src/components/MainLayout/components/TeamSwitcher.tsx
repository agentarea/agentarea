"use client";

import * as React from "react";
import { ChevronsUpDown, Crown, Globe, Plus, Sparkles, Users, Zap } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
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
  const [proDialogOpen, setProDialogOpen] = React.useState(false);

  if (!activeTeam) {
    return null;
  }

  const proFeatures = [
    { icon: Globe, title: "Multiple Workspaces", description: "Isolate teams, clients, or environments" },
    { icon: Users, title: "Team Collaboration", description: "Invite members with role-based access" },
    { icon: Zap, title: "Priority Execution", description: "Faster agent runs with dedicated resources" },
    { icon: Sparkles, title: "Advanced Analytics", description: "Deep insights into agent performance" },
  ];

  return (
    <>
    <Dialog open={proDialogOpen} onOpenChange={setProDialogOpen}>
      <DialogContent className="sm:max-w-lg p-0 overflow-hidden">
        <div className="bg-gradient-to-br from-primary/10 via-primary/5 to-transparent px-6 pt-6 pb-4">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-xl">
              <Crown className="h-5 w-5 text-primary" />
              Upgrade to Pro
            </DialogTitle>
            <p className="text-sm text-muted-foreground mt-1">
              Unlock powerful features to scale your agent organization
            </p>
          </DialogHeader>
        </div>
        <div className="px-6 pb-2">
          <div className="space-y-1">
            {proFeatures.map((feature) => (
              <div key={feature.title} className="flex items-start gap-3 rounded-lg p-3 transition-colors hover:bg-muted/50">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                  <feature.icon className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <p className="text-sm font-medium">{feature.title}</p>
                  <p className="text-xs text-muted-foreground">{feature.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <DialogFooter className="px-6 py-4 border-t bg-muted/30">
          <Button variant="outline" onClick={() => setProDialogOpen(false)}>
            Maybe later
          </Button>
          <Button onClick={() => window.open("https://agentarea.ai/pricing", "_blank")}>
            <Crown className="h-4 w-4 mr-2" />
            Get AgentArea Pro
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

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
                  <img
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
                    <img
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
            <DropdownMenuItem
              className="gap-2 p-2 cursor-pointer"
              onSelect={() => {
                setTimeout(() => setProDialogOpen(true), 0);
              }}
            >
              <div className="flex size-6 items-center justify-center rounded-md border bg-primary/10">
                <Plus className="size-4 text-primary" />
              </div>
              <span className="text-sm font-medium">Add Workspace</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
    </>
  );
}
