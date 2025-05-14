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
import { LucideProps } from "lucide-react";
import Header from "./components/Header";
import SideBarWrapper from "./components/SideBarWrapper";

export type NavSection = {
  id: string;
  section?: string;
  labelKey?: string;
  icon?: React.ReactElement<LucideProps>;
  items: {
    label: string;
    labelKey?: string;
    href: string;
    icon?: React.ReactElement<LucideProps>;
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
    id: "main",
    items: [
      {
        label: "Workplace",
        labelKey: "workplace",
        href: "/workplace",
        icon: <Home />,
      },
      {
        label: "Browse",
        labelKey: "browse",
        href: "/agents/browse",
        icon: <Bot />,
      },
      {
        label: "Workflows",
        labelKey: "workflows",
        href: "/agents/workflows",
        icon: <ClipboardList />,
      },
      {
        label: "Connections",
        labelKey: "connections",
        href: "/mcp-servers",
        icon: <Plug />,
      },
      {
        label: "LLM Models",
        labelKey: "llms",
        href: "/admin/llms",
        icon: <Cpu />,
      }
    ],
  },
];

// export const navContent: NavSection[] = [
//   {
//     id: "workplace",
//     items: [
//       {
//         label: "Workplace",
//         labelKey: "workplace",
//         href: "/workplace",
//         icon: <Home />,
//       },
//     ],
//   },
//   {
//     id: "agents",
//     labelKey: "agents",
//     section: "Agents",
//     icon: <Bot />,
//     items: [
//       {
//         label: "Browse",
//         labelKey: "browse",
//         href: "/agents/browse",
//         icon: <Bot />,
//       },
//       {
//         label: "Workflows",
//         labelKey: "workflows",
//         href: "/agents/workflows",
//         icon: <ClipboardList />,
//       },
//     ],
//   },
//   {
//     id: "mcp",
//     labelKey: "mcp",
//     section: "MCP Servers",
//     icon: <Server />,
//     items: [
//       {
//         label: "Connections",
//         labelKey: "connections",
//         href: "/mcp-servers",
//         icon: <Plug />,
//       },
//     ],
//   },
//   {
//     id: "admin",
//     labelKey: "admin",
//     section: "Admin",
//     icon: <Settings />,
//     items: [
//       {
//         label: "LLM Models",
//         labelKey: "llms",
//         href: "/admin/llms",
//         icon: <Cpu />,
//       },
//     ],
//   },
//   // Commented out sections
//   /*
//   {
//     id: "scopes",
//     section: "Scopes",
//     icon: <Building2 />,
//     items: [
//       {
//         label: "All Scopes",
//         href: "/scopes",
//         icon: <Building2 />,
//       },
//       {
//         label: "Projects",
//         href: "/scopes?type=project",
//         icon: <Globe />,
//       },
//       {
//         label: "Teams",
//         href: "/scopes?type=team",
//         icon: <Users />,
//       },
//       {
//         label: "Departments",
//         href: "/scopes?type=department",
//         icon: <Building2 />,
//       },
//     ],
//   },
//   {
//     id: "sources",
//     section: "Sources",
//     icon: <Database />,
//     items: [
//       {
//         label: "Browse",
//         href: "/sources/browse",
//         icon: <Database />,
//       },
//     ],
//   },
//   {
//     id: "catalog",
//     section: "Catalog",
//     icon: <ShoppingBag />,
//     items: [
//       {
//         label: "Browse",
//         href: "/marketplace/browse",
//         icon: <ShoppingBag />,
//       },
//     ],
//   },
//   */
// ];

const bottomNavContent: BottomNavContent = {
  id: "settings",
  items: [
    {
      label: "Settings",
      labelKey: "settings",
      href: "/settings",
      icon: <Settings />,
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
        <SideBarWrapper
          menuContent={navContent}
          bottomMenuContent={bottomNavContent}
        />
        <Header menuContent={navContent} bottomMenuContent={bottomNavContent} />
        <main className="flex-1 overflow-hidden pb-[10px] md:pt-[10px] pr-[10px] max-md:px-[10px] max-h-screen">
          <div className=" bg-white dark:bg-zinc-900 rounded-xl h-full border border-zinc-200 dark:border-zinc-700 overflow-y-auto">
            {children}
          </div>
        </main>
      </div>
      {/* <ThemeToggle className="absolute bottom-2 right-2" /> */}
    </>
  );
}
