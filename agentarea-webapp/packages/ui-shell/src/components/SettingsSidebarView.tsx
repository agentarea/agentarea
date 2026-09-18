"use client";

import { ArrowLeft, Github } from "lucide-react";
import {
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "./ui/sidebar";
import { cn } from "../lib/utils";

/** One nav entry. `icon` is any lucide-style component. */
export type SettingsNavItem = {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
};

export type SettingsNavSection = {
  label: string;
  items: SettingsNavItem[];
};

export type SettingsSidebarViewProps = {
  /** Heading of the sidebar — "Settings". */
  title: string;
  /** Sub-label and tooltip of the back button — "Back to app". */
  backToApp: string;
  /** Where the back button goes. An absolute URL when it leaves this deployment. */
  backHref: string;
  sections: SettingsNavSection[];
  /** Current path, used to mark the active entry. */
  currentPath: string;
  /** Rendered at the bottom, under the social links. The account menu, normally. */
  footer?: React.ReactNode;
  /**
   * Link component. Defaults to a plain anchor, which is also the right choice for an
   * app served under a basePath: next/link would prefix every href with it, and these
   * hrefs point at the platform, not at the app rendering them.
   */
  linkComponent?: React.ComponentType<{
    href: string;
    className?: string;
    children: React.ReactNode;
  }>;
};

/**
 * The settings sidebar, with nothing of any particular app in it.
 *
 * Presentational on purpose: it takes its entries, labels and the current path rather
 * than reading next-intl, the router and the session. Not because those are unwelcome —
 * a consumer is free to use next-intl to produce these props, and the platform does —
 * but because a deployment that lacks them must still be able to render this. That is
 * what lets the billing UI, a separate Next app, show the same sidebar instead of
 * growing its own shell, which is how the two came to look like unrelated products.
 */
export function SettingsSidebarView({
  title,
  backToApp,
  backHref,
  sections,
  currentPath,
  footer,
  linkComponent,
}: SettingsSidebarViewProps) {
  const { open } = useSidebar();
  const LinkComponent =
    linkComponent ??
    (({ href, className, children }) => (
      <a href={href} className={className}>
        {children}
      </a>
    ));

  const isActive = (href: string) =>
    href === "/settings"
      ? currentPath === "/settings"
      : currentPath.startsWith(href);

  return (
    <>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild size="lg" tooltip={backToApp}>
              <LinkComponent href={backHref} className="flex items-center gap-2">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-zinc-100 dark:bg-zinc-800">
                  <ArrowLeft className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">{title}</span>
                  <span className="truncate text-[10px] text-muted-foreground">
                    {backToApp}
                  </span>
                </div>
              </LinkComponent>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {sections.map((section) => (
          <SidebarGroup key={section.label}>
            <SidebarGroupLabel>{section.label}</SidebarGroupLabel>
            <SidebarMenu>
              {section.items.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(item.href)}
                    tooltip={item.title}
                  >
                    <LinkComponent href={item.href}>
                      <item.icon />
                      <span>{item.title}</span>
                    </LinkComponent>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter
        className={cn(`flex flex-col overflow-hidden`, !open && "items-center")}
      >
        <div
          className={cn(
            "flex items-center justify-center gap-4 py-2 text-muted-foreground/50",
            !open && "flex-col gap-2"
          )}
        >
          <a
            href="https://github.com/agentarea/agentarea"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-muted-foreground transition-colors"
            title="GitHub"
          >
            <Github className="h-4 w-4" />
          </a>
          <a
            href="https://x.com/agentarea_hq"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-muted-foreground transition-colors"
            title="X (Twitter)"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
          </a>
          <a
            href="https://discord.gg/5tduPwheYQ"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-muted-foreground transition-colors"
            title="Discord"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
              <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.947 2.418-2.157 2.418z" />
            </svg>
          </a>
        </div>
        {footer}
      </SidebarFooter>
    </>
  );
}
