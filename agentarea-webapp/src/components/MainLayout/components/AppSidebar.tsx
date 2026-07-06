"use client";

import * as React from "react";
import { Github, SquarePen } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  SidebarFooter,
  SidebarHeader,
  useSidebar,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { QUICK_TASK_OPEN_EVENT } from "@/components/QuickTask/QuickTaskDialog";
import { APP_VERSION } from "@/lib/app-version";
import { cn } from "@/lib/utils";
import { NavMain } from "./NavMain";
import { NavUser } from "./NavUser";
import { SidebarNavScroll } from "./SidebarNavScroll";
import { TeamSwitcher } from "./TeamSwitcher";

function SocialLinks({ iconClass }: { iconClass: string }) {
  return (
    <>
      <a
        href="https://github.com/agentarea/agentarea"
        target="_blank"
        rel="noopener noreferrer"
        className="text-muted-foreground/45 transition-colors hover:text-muted-foreground"
        title="GitHub"
      >
        <Github className={iconClass} />
      </a>
      <a
        href="https://x.com/agentarea_hq"
        target="_blank"
        rel="noopener noreferrer"
        className="text-muted-foreground/45 transition-colors hover:text-muted-foreground"
        title="X (Twitter)"
      >
        <svg className={iconClass} viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" /></svg>
      </a>
      <a
        href="https://discord.gg/5tduPwheYQ"
        target="_blank"
        rel="noopener noreferrer"
        className="text-muted-foreground/45 transition-colors hover:text-muted-foreground"
        title="Discord"
      >
        <svg className={iconClass} viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.947 2.418-2.157 2.418z" /></svg>
      </a>
    </>
  );
}

export function AppSidebarContent({ data }: { data: any }) {
  const { open } = useSidebar();
  const router = useRouter();

  const openQuickTask = React.useCallback(() => {
    if (typeof window === "undefined") return;
    window.dispatchEvent(new CustomEvent(QUICK_TASK_OPEN_EVENT));
  }, []);

  return (
    <>
      <SidebarHeader>
        <TeamSwitcher teams={data.workspaces} />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className={cn(
                "group h-8 w-full justify-start gap-2 rounded-md px-2 text-[13px] font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                !open && "justify-center px-0"
              )}
              onClick={openQuickTask}
            >
              <SquarePen className="h-3.5 w-3.5 shrink-0 text-muted-foreground/80 group-hover:text-foreground" />
              {open && (
                <>
                  <span className="flex-1 truncate text-left">New task</span>
                  <Kbd keys={["⌘", "J"]} className="ml-auto hidden sm:inline-flex" />
                </>
              )}
            </Button>
          </TooltipTrigger>
          {!open && (
            <TooltipContent side="right">
              New task <kbd className="ml-1 text-[10px]">&#8984;J</kbd>
            </TooltipContent>
          )}
        </Tooltip>
      </SidebarHeader>
      <SidebarNavScroll>
        <NavMain sections={data.navSections} />
      </SidebarNavScroll>
      <SidebarFooter
        className={cn(
          `flex flex-col overflow-hidden border-t border-sidebar-border/60 gap-1.5`,
          !open && "items-center"
        )}
      >
        <div
          className={cn(
            "flex items-center justify-center gap-5 pb-0.5 pt-1 text-muted-foreground/50",
            !open && "flex-col gap-2"
          )}
        >
          <SocialLinks iconClass="h-[14px] w-[14px]" />
        </div>
        <NavUser />
        {open && (
          <div className="flex items-center justify-center pb-1 text-[10px] text-muted-foreground/40">
            v{APP_VERSION}
          </div>
        )}
      </SidebarFooter>
    </>
  );
}
