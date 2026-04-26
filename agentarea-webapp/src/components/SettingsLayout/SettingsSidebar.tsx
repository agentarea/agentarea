"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  CreditCard,
  Download,
  Github,
  Key,
  ScrollText,
  User,
} from "lucide-react";
import { NavUser } from "@/components/MainLayout/components/NavUser";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { APP_VERSION } from "@/lib/app-version";
import { cn } from "@/lib/utils";

export function SettingsSidebarContent() {
  const pathname = usePathname();
  const t = useTranslations("SettingsSidebar");
  const { open } = useSidebar();

  const settingsNav = [
    {
      label: t("account"),
      items: [
        { title: t("profile"), href: "/settings", icon: User },
        { title: t("billing"), href: "/settings/billing", icon: CreditCard },
      ],
    },
    {
      label: t("workspace"),
      items: [
        { title: t("apiKeys"), href: "/admin/api-keys", icon: Key },
        { title: t("importExport"), href: "/admin/workspace", icon: Download },
        { title: t("auditLog"), href: "/settings/audit", icon: ScrollText },
      ],
    },
  ];

  const isActive = (href: string) =>
    href === "/settings" ? pathname === "/settings" : pathname.startsWith(href);

  return (
    <>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild size="lg" tooltip={t("backToApp")}>
              <Link href="/workplace" className="flex items-center gap-2">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-zinc-100 dark:bg-zinc-800">
                  <ArrowLeft className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">{t("title")}</span>
                  <span className="truncate text-[10px] text-muted-foreground">
                    {t("backToApp")}
                  </span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {settingsNav.map((section) => (
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
                    <Link href={item.href as any}>
                      <item.icon />
                      <span>{item.title}</span>
                    </Link>
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

export default function SettingsSidebar() {
  return (
    <Sidebar collapsible="icon">
      <SettingsSidebarContent />
    </Sidebar>
  );
}
