import {
  Bot,
  Brain,
  ClipboardList,
  Compass,
  FileText,
  GalleryVerticalEnd,
  Gauge,
  Home,
  Inbox,
  KeyRound,
  Network,
  Plug,
  ShieldCheck,
  Sparkles,
  Users,
  Wallet,
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
      logoFile: "/Icon.svg",
    },
  ],
  navSections: [
    {
      label: "Work",
      labelKey: "work",
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
          title: "Tasks",
          titleKey: "tasks",
          url: "/tasks",
          icon: ClipboardList,
        },
        // Projects nav item hidden until the feature is fully working.
        // Tracked in GitHub: finish the Projects feature before re-enabling.
      ],
    },
    {
      label: "Knowledge",
      labelKey: "knowledge",
      items: [
        {
          title: "Context",
          titleKey: "context",
          url: "/files",
          icon: FileText,
        },
      ],
    },
    {
      label: "Build",
      labelKey: "build",
      items: [
        {
          title: "Explore",
          titleKey: "explore",
          url: "/explore",
          icon: Compass,
        },
        {
          title: "Agents",
          titleKey: "agents",
          url: "/agents",
          icon: Bot,
        },
        {
          title: "Skills",
          titleKey: "skills",
          url: "/skills",
          icon: Sparkles,
        },
        {
          title: "Connections",
          titleKey: "connections",
          url: "/mcp-servers",
          icon: Plug,
        },
        {
          title: "Models",
          titleKey: "providerConfigs",
          url: "/admin/provider-configs",
          icon: Brain,
        },
        {
          title: "Automation",
          titleKey: "automation",
          url: "/triggers",
          icon: Zap,
        },
      ],
    },
    {
      label: "Govern",
      labelKey: "govern",
      items: [
        {
          title: "Dashboard",
          titleKey: "dashboard",
          url: "/dashboard",
          icon: Gauge,
        },
        {
          title: "Network",
          titleKey: "network",
          url: "/network",
          icon: Network,
        },
        {
          title: "Members",
          titleKey: "members",
          url: "/members",
          icon: Users,
        },
        {
          title: "Budgets",
          titleKey: "budgets",
          url: "/budgets",
          icon: Wallet,
        },
        {
          title: "Secrets",
          titleKey: "secrets",
          url: "/secrets",
          icon: KeyRound,
        },
        {
          title: "Policies",
          titleKey: "policies",
          url: "/policies",
          icon: ShieldCheck,
        },
      ],
    },
  ],
};
