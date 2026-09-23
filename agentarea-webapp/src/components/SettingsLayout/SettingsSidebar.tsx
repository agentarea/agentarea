"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  CreditCard,
  Key,
  ScrollText,
  User,
} from "lucide-react";
import { AppSidebarFooter } from "@/components/MainLayout/components/AppSidebarFooter";
import { navItemClassName } from "@/components/MainLayout/components/NavMain";
import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useBillingUrl } from "@/lib/use-billing-url";

export function SettingsSidebarContent() {
  const pathname = usePathname();
  const t = useTranslations("SettingsSidebar");
  // Empty on any deployment that does not sell, which is the open default.
  const billingUrl = useBillingUrl();

  const settingsNav = [
    {
      label: t("account"),
      items: [
        { title: t("profile"), href: "/settings", icon: User },
        ...(billingUrl
          ? [{ title: t("billing"), href: billingUrl, icon: CreditCard }]
          : []),
      ],
    },
    {
      label: t("workspace"),
      items: [
        { title: t("apiKeys"), href: "/settings/api-keys", icon: Key },
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
                    className={navItemClassName}
                  >
                    <Link href={item.href}>
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
      <AppSidebarFooter />
    </>
  );
}
