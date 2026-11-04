"use client";

import { useTranslations } from "next-intl";
import { BookOpen, CircleHelp, LifeBuoy } from "lucide-react";
import { DiscordIcon, GitHubIcon } from "@/components/brand-icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useClientEnv } from "@/lib/use-client-env";
import { navItemClassName } from "./NavMain";

const DOCS_URL = "https://docs.agentarea.ai";
const GITHUB_URL = "https://github.com/agentarea/agentarea";
const DISCORD_URL = "https://discord.gg/5tduPwheYQ";

function ExternalItem({
  href,
  icon,
  label,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <DropdownMenuItem asChild className="cursor-pointer">
      <a href={href} target="_blank" rel="noopener noreferrer">
        {icon}
        {label}
      </a>
    </DropdownMenuItem>
  );
}

/** The last row of the sidebar nav: support, docs and the community, behind one menu. */
export function NavHelp() {
  const t = useTranslations("NavHelp");
  const { isMobile } = useSidebar();
  const supportUrl = useClientEnv("CLIENT_SUPPORT_URL");

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              tooltip={t("title")}
              className={navItemClassName}
            >
              <CircleHelp />
              <span>{t("title")}</span>
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="min-w-56 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="start"
            sideOffset={4}
          >
            {supportUrl ? (
              <>
                <ExternalItem
                  href={supportUrl}
                  icon={<LifeBuoy className="mr-2 size-4" />}
                  label={t("support")}
                />
                <DropdownMenuSeparator />
              </>
            ) : null}
            <ExternalItem
              href={DOCS_URL}
              icon={<BookOpen className="mr-2 size-4" />}
              label={t("docs")}
            />
            <ExternalItem
              href={GITHUB_URL}
              icon={<GitHubIcon className="mr-2 size-4" />}
              label="GitHub"
            />
            <ExternalItem
              href={DISCORD_URL}
              icon={<DiscordIcon className="mr-2 size-4" />}
              label={t("discord")}
            />
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
