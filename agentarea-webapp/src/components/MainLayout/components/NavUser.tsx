"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { CreditCard, LogOut, Settings } from "lucide-react";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useAuth } from "@/hooks/useAuth";
import { APP_VERSION } from "@/lib/app-version";

/**
 * Where this deployment's billing page lives, if it has one.
 *
 * An open install has nothing to bill for, so there is no billing page here and no link
 * to one. A deployment that sells sets NEXT_PUBLIC_BILLING_URL and serves that page
 * itself; this repository holds the URL and nothing else about it -- no balance, no
 * prices, no provider, no plans.
 */
const BILLING_URL = process.env.NEXT_PUBLIC_BILLING_URL?.trim();

export function NavUser() {
  const t = useTranslations("NavUser");
  const { isMobile } = useSidebar();
  const { user: authUser, isLoaded, signOut } = useAuth();
  const user = authUser
    ? {
        name: authUser.name || "User",
        email: authUser.email || "",
        avatar: authUser.image || "",
      }
    : null;

  const handleLogout = async () => {
    await signOut();
  };

  if (!isLoaded) {
    return null;
  }

  if (!user) {
    return null;
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="!h-auto gap-2.5 py-1.5 data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground transition-all duration-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              <EntityAvatar
                size={28}
                src={user.avatar || undefined}
                alt={user.name}
                text={nameInitials(user.name)}
              />
              <div className="grid flex-1 text-left leading-tight">
                <span className="truncate text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
                  {user.name}
                </span>
                <span className="truncate text-[11px] text-zinc-500/80">
                  {user.email}
                </span>
              </div>
              {/* <ChevronsUpDown className="ml-auto size-4" /> */}
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuLabel className="p-0 font-normal">
              <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                <EntityAvatar
                  size={32}
                  src={user.avatar || undefined}
                  alt={user.name}
                  text={nameInitials(user.name)}
                />
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-medium">{user.name}</span>
                  <span className="truncate text-xs">{user.email}</span>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {/* <DropdownMenuGroup>
              <DropdownMenuItem>
                <Sparkles />
                Upgrade to Pro
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator /> */}
            <DropdownMenuGroup>
              <DropdownMenuItem asChild className="cursor-pointer">
                <Link href="/settings" className="flex w-full items-center">
                  <Settings className="mr-2 size-4" />
                  {t("settings")}
                </Link>
              </DropdownMenuItem>
              {BILLING_URL ? (
                <DropdownMenuItem asChild className="cursor-pointer">
                  <Link
                    href={BILLING_URL}
                    className="flex w-full items-center"
                  >
                    <CreditCard className="mr-2 size-4" />
                    {t("billing")}
                  </Link>
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout}>
              <LogOut className="mr-2 size-4" />
              {t("logout")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <div className="px-2 py-1 text-[10px] text-muted-foreground/50">
              AgentArea v{APP_VERSION}
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
