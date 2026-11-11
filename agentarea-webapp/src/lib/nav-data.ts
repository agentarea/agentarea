import {
  AppWindow,
  Bot,
  Brain,
  ClipboardList,
  FileText,
  GalleryVerticalEnd,
  Gauge,
  Hammer,
  Inbox,
  KeyRound,
  LayoutGrid,
  Library,
  MessagesSquare,
  Network,
  Plug,
  Radio,
  ShieldCheck,
  SlidersHorizontal,
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
      collapsible: false,
      items: [
        {
          title: "Dashboard",
          titleKey: "dashboard",
          url: "/dashboard",
          icon: Gauge,
        },
        {
          title: "Inbox",
          titleKey: "inbox",
          url: "/inbox",
          icon: Inbox,
        },
        {
          title: "Apps",
          titleKey: "apps",
          url: "/apps",
          icon: AppWindow,
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
      icon: Library,
      items: [
        {
          title: "Context",
          titleKey: "context",
          url: "/files",
          icon: FileText,
        },
        {
          title: "Events",
          titleKey: "events",
          url: "/events",
          icon: Radio,
        },
      ],
    },
    {
      label: "Build",
      labelKey: "build",
      icon: Hammer,
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
          title: "Harnesses",
          titleKey: "clients",
          url: "/clients",
          icon: Terminal,
        },
        {
          title: "Automation",
          titleKey: "automation",
          url: "/triggers",
          icon: Zap,
        },
        {
          title: "Channels",
          titleKey: "channels",
          url: "/channels",
          icon: MessagesSquare,
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
      label: "Control",
      labelKey: "control",
      icon: SlidersHorizontal,
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
