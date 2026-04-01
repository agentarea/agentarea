import {
  Bot,
  Brain,
  ClipboardList,
  FolderKanban,
  GalleryVerticalEnd,
  Home,
  Inbox,
  Network,
  Plug,
  Sparkles,
  Zap,
} from "lucide-react";
import type { LucideProps } from "lucide-react";

export type NavSection = {
  id: string;
  section?: string;
  labelKey?: string;
  isCollapsed?: boolean;
  icon?: React.ReactElement<LucideProps>;
  items: {
    title: string;
    titleKey?: string;
    url: string;
    icon?: any;
  }[];
};

export const navData = {
  workspaces: [
    {
      name: "AgentArea",
      logo: GalleryVerticalEnd,
      plan: "Base workspace",
      logoFile: "/starlogo.svg",
    },
  ],
  navSections: [
    {
      items: [
        {
          title: "Home",
          titleKey: "home",
          url: "/workplace",
          icon: Home,
        },
        {
          title: "Inbox",
          titleKey: "inbox",
          url: "/inbox",
          icon: Inbox,
        },
        {
          title: "Projects",
          titleKey: "projects",
          url: "/projects",
          icon: FolderKanban,
        },
        {
          title: "Agents",
          titleKey: "agents",
          url: "/agents",
          icon: Bot,
        },
        {
          title: "Tasks",
          titleKey: "tasks",
          url: "/tasks",
          icon: ClipboardList,
        },
      ],
    },
    {
      label: "Platform",
      labelKey: "platform",
      items: [
        {
          title: "Models",
          titleKey: "providerConfigs",
          url: "/admin/provider-configs",
          icon: Brain,
        },
        {
          title: "Connections",
          titleKey: "connections",
          url: "/mcp-servers",
          icon: Plug,
        },
        {
          title: "Skills",
          titleKey: "skills",
          url: "/skills",
          icon: Sparkles,
        },
        {
          title: "Automation",
          titleKey: "automation",
          url: "/triggers",
          icon: Zap,
        },
        {
          title: "Network",
          titleKey: "network",
          url: "/network",
          icon: Network,
        },
      ],
    },
  ],
};
