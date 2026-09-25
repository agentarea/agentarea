import {
  AppWindow,
  Bot,
  Brain,
  ClipboardList,
  FileText,
  GalleryVerticalEnd,
  Gauge,
  KeyRound,
  LayoutGrid,
  Network,
  Plug,
  ShieldCheck,
  Sparkles,
  Terminal,
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
    icon?: React.ElementType;
  }[];
};

export const navData = {
  navSections: [
    {
      label: "Work",
      labelKey: "work",
      collapsible: false,
      items: [
        {
          title: "Dashboard",
          titleKey: "dashboard",
          url: "/dashboard",
          icon: Gauge,
        },
        {
          title: "Tasks",
          titleKey: "tasks",
          url: "/tasks",
          icon: ClipboardList,
        },
        {
          title: "Projects",
          titleKey: "projects",
          url: "/projects",
          icon: GalleryVerticalEnd,
        },
        {
          title: "Automation",
          titleKey: "automation",
          url: "/triggers",
          icon: Zap,
        },
        {
          title: "Catalog",
          titleKey: "explore",
          url: "/explore",
          icon: LayoutGrid,
        },
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
          url: "/connections",
          icon: Plug,
        },
        {
          title: "Apps",
          titleKey: "apps",
          url: "/apps",
          icon: AppWindow,
        },
        {
          title: "Harnesses",
          titleKey: "clients",
          url: "/clients",
          icon: Terminal,
        },
        {
          title: "Models",
          titleKey: "providerConfigs",
          url: "/models",
          icon: Brain,
        },
      ],
    },
    {
      label: "Govern",
      labelKey: "govern",
      items: [
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
