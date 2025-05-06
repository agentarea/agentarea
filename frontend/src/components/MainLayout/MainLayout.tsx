// import { ThemeToggle } from "@/components/ui/theme-toggle";
import {
  Bot,
  Home,
  Settings,
  Server,
  Cpu,
  Package,
  Plug,
  ClipboardList,
} from "lucide-react";
import Header from "./components/Header";
import SideBar from "./components/SideBar";

export type NavSection = {
  id: string;
  section?: string;
  labelKey?: string;
  icon?: React.ReactElement;
  items: {
    label: string;
    labelKey?: string;
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
        labelKey: "workplace",
        href: "/workplace",
        icon: <Home className="h-5 w-5" />,
      },
    ],
  },
  {
    id: "agents",
    labelKey: "agents",
    section: "Agents",
    icon: <Bot className="h-5 w-5" />,
    items: [
      {
        label: "Browse",
        labelKey: "browse",
        href: "/agents/browse",
        icon: <Bot className="h-5 w-5" />,
      },
      {
        label: "Workflows",
        labelKey: "workflows",
        href: "/agents/workflows",
        icon: <ClipboardList className="h-5 w-5" />,
      },
    ],
  },
  {
    id: "mcp",
    labelKey: "mcp",
    section: "MCP Servers",
    icon: <Server className="h-5 w-5" />,
    items: [
      {
        label: "Connections",
        labelKey: "connections",
        href: "/mcp-servers",
        icon: <Plug className="h-5 w-5" />,
      },
    ],
  },
  {
    id: "admin",
    labelKey: "admin",
    section: "Admin",
    icon: <Settings className="h-5 w-5" />,
    items: [
      {
        label: "LLM Models",
        labelKey: "llms",
        href: "/admin/llms",
        icon: <Cpu className="h-5 w-5" />,
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
      labelKey: "settings",
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
      <div className="flex md:flex-row flex-col h-screen w-screen overflow-hidden bg-zinc-100 dark:bg-zinc-800"
      // style={{ backgroundImage: "url('/bg.png')", backgroundSize: "cover", backgroundPosition: "right" }}
      >
        <SideBar
          menuContent={navContent}
          bottomMenuContent={bottomNavContent}
        />
        <Header menuContent={navContent} bottomMenuContent={bottomNavContent} />
        <main className="flex-1 overflow-hidden py-[10px] pr-[10px] max-md:px-[10px] max-h-screen">
          <div className=" bg-white dark:bg-zinc-900 rounded-xl h-full border border-zinc-200 dark:border-zinc-700 overflow-y-auto">
            {children}
          </div>
        </main>
      </div>
      {/* <ThemeToggle className="absolute bottom-2 right-2" /> */}
    </>
  );
}
