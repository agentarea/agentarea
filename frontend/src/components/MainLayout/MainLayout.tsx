import { ThemeToggle } from "@/components/ui/theme-toggle";
import {
  Bot,
  Home,
  Settings,
  Server,
  Cpu,
  Package,
  ClipboardList,
} from "lucide-react";
import Header from "./components/Header";
import SideBar from "./components/SideBar";

export type NavSection = {
  id: string;
  section?: string;
  icon?: React.ReactElement;
  items: {
    label: string;
    href: string;
    icon?: React.ReactElement;
  }[];
};

export type BottomNavContent = {
  user: {
    name: string;
    email: string;
    avatar: string;
  };
} & NavSection;

export const navContent: NavSection[] = [
  {
    id: "workplace",
    items: [
      {
        label: "Workplace",
        href: "/workplace",
        icon: <Home className="h-5 w-5" />,
      },
    ],
  },
  {
    id: "agents",
    section: "Agents",
    icon: <Bot className="h-5 w-5" />,
    items: [
      {
        label: "Browse",
        href: "/agents/browse",
        icon: <Bot className="h-5 w-5" />,
      },
      {
        label: "Workflows",
        href: "/agents/workflows",
        icon: <ClipboardList className="h-5 w-5" />,
      },
    ],
  },
  {
    id: "llms",
    section: "LLM Models",
    icon: <Cpu className="h-5 w-5" />,
    items: [
      {
        label: "Browse",
        href: "/llms/browse",
        icon: <Cpu className="h-5 w-5" />,
      },
      // {
      //   label: "Add Model",
      //   href: "/marketplace/llms/create",
      //   icon: <Package className="h-5 w-5" />,
      // },
    ],
  },
  {
    id: "mcp",
    section: "MCP Servers",
    icon: <Server className="h-5 w-5" />,
    items: [
      {
        label: "Servers",
        href: "/mcp-servers",
        icon: <Server className="h-5 w-5" />,
      },
    ],
  },
  // Commented out sections
  /*
  {
    id: "scopes",
    section: "Scopes",
    icon: <Building2 className="h-5 w-5" />,
    items: [
      {
        label: "All Scopes",
        href: "/scopes",
        icon: <Building2 className="h-5 w-5" />,
      },
      {
        label: "Projects",
        href: "/scopes?type=project",
        icon: <Globe className="h-5 w-5" />,
      },
      {
        label: "Teams",
        href: "/scopes?type=team",
        icon: <Users className="h-5 w-5" />,
      },
      {
        label: "Departments",
        href: "/scopes?type=department",
        icon: <Building2 className="h-5 w-5" />,
      },
    ],
  },
  {
    id: "sources",
    section: "Sources",
    icon: <Database className="h-5 w-5" />,
    items: [
      {
        label: "Browse",
        href: "/sources/browse",
        icon: <Database className="h-5 w-5" />,
      },
    ],
  },
  {
    id: "catalog",
    section: "Catalog",
    icon: <ShoppingBag className="h-5 w-5" />,
    items: [
      {
        label: "Browse",
        href: "/marketplace/browse",
        icon: <ShoppingBag className="h-5 w-5" />,
      },
    ],
  },
  */
];

const bottomNavContent: BottomNavContent = {
  id: "settings",
  items: [
    {
      label: "Settings",
      href: "/settings",
      icon: <Settings className="h-5 w-5" />,
    },
  ],
  user: {
    name: "Admin",
    email: "admin@admin.com",
    avatar: "https://github.com/shadcn.png",
  },
};

export default function MainLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <div className="flex md:flex-row flex-col h-screen w-screen overflow-hidden">
        <SideBar
          menuContent={navContent}
          bottomMenuContent={bottomNavContent}
        />
        <Header menuContent={navContent} bottomMenuContent={bottomNavContent} />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
      <ThemeToggle className="absolute bottom-2 right-2" />
    </>
  );
}
