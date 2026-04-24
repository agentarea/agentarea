"use client";

import * as React from "react";
import { Github, SquarePen } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { APP_VERSION } from "@/lib/app-version";
import { cn } from "@/lib/utils";
import { NavMain } from "./NavMain";
import { NavUser } from "./NavUser";
import { TeamSwitcher } from "./TeamSwitcher";

export function AppSidebarContent({ data }: { data: any }) {
  const { open } = useSidebar();
  const router = useRouter();

  // Cmd+J → open workplace (new task)
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "j") {
        e.preventDefault();
        router.push("/workplace");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [router]);

  return (
    <>
      <SidebarHeader>
        <TeamSwitcher teams={data.workspaces} />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              className={cn(
                "w-full justify-start gap-2",
                !open && "justify-center px-2"
              )}
              onClick={() => router.push("/workplace")}
            >
              <SquarePen className="h-4 w-4 shrink-0" />
              {open && (
                <>
                  <span className="flex-1 text-left">New Task</span>
                  <kbd className="pointer-events-none ml-auto hidden h-5 select-none items-center gap-0.5 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground sm:flex">
                    <span className="text-xs">&#8984;</span>J
                  </kbd>
                </>
              )}
            </Button>
          </TooltipTrigger>
          {!open && (
            <TooltipContent side="right">
              New Task <kbd className="ml-1 text-[10px]">&#8984;J</kbd>
            </TooltipContent>
          )}
        </Tooltip>
      </SidebarHeader>
      <SidebarContent>
        <NavMain sections={data.navSections} />
      </SidebarContent>
      <SidebarFooter
        className={cn(
          `flex flex-col overflow-hidden`,
          !open && "items-center"
        )}
      >
        <div className={cn(
          "flex items-center justify-center gap-4 py-2 text-muted-foreground/50",
          !open && "flex-col gap-2"
        )}>
          <a href="https://github.com/agentarea/agentarea" target="_blank" rel="noopener noreferrer" className="hover:text-muted-foreground transition-colors" title="GitHub">
            <Github className="h-4 w-4" />
          </a>
          <a href="https://x.com/agentarea_hq" target="_blank" rel="noopener noreferrer" className="hover:text-muted-foreground transition-colors" title="X (Twitter)">
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" /></svg>
          </a>
          <a href="https://discord.gg/5tduPwheYQ" target="_blank" rel="noopener noreferrer" className="hover:text-muted-foreground transition-colors" title="Discord">
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.947 2.418-2.157 2.418z" /></svg>
          </a>
        </div>
        <NavUser />
        {open && (
          <div className="flex items-center justify-center pb-1 text-[10px] text-muted-foreground/40">
            v{APP_VERSION}
          </div>
        )}
      </SidebarFooter>
      <SidebarRail />
    </>
  );
}

export function AppSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar> & { data: any }) {
  return (
    <Sidebar
      collapsible="icon"
      {...props}
      className=""
    >
      <AppSidebarContent data={props.data} />
    </Sidebar>
  );
}
