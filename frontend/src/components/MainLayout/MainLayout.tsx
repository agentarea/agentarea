import { ThemeToggle } from "@/components/ui/theme-toggle";
import {
  Bot,
  Home,
  Settings,
  Plug,
  ClipboardList,
  Key,
  GalleryVerticalEnd,
  AudioWaveform,
  Command,
  SquareTerminal,
} from "lucide-react";
import { LucideProps } from "lucide-react";
import Header from "./components/Header";
import SideBarWrapper from "./components/SideBarWrapper";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "./components/AppSidebar";

export type NavSection = {
  id: string;
  section?: string;
  labelKey?: string;
  isCollapsed?: boolean;
  icon?: React.ReactElement<LucideProps>;
  items: {
    label: string;
    labelKey?: string;
    href: string;
    icon?: React.ReactElement<LucideProps>;
  }[];
};

export type BottomNavContent = {
  user?: {
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
        label: "Tasks",
        labelKey: "tasks",
        href: "/tasks",
        icon: <ClipboardList />,
      },
      {
        label: "Connections",
        labelKey: "connections",
        href: "/mcp-servers",
        icon: <Plug />,
      },
    ],
  },
  {
    id: "admin",
    labelKey: "admin",
    section: "Admin",
    icon: <Settings />,
    isCollapsed: true,
    items: [
      {
        label: "Models",
        labelKey: "providerConfigs",
        href: "/admin/provider-configs",
        icon: <Key />,
      },
    ],
  },
];

const data = {
  // user: {
  //   name: "shadcn",
  //   email: "m@example.com",
  //   avatar: "/avatars/shadcn.jpg",
  // },
  // teams: [
  //   {
  //     name: "Acme Inc",
  //     logo: GalleryVerticalEnd,
  //     plan: "Enterprise",
  //   },
  //   {
  //     name: "Acme Corp.",
  //     logo: AudioWaveform,
  //     plan: "Startup",
  //   },
  //   {
  //     name: "Evil Corp.",
  //     logo: Command,
  //     plan: "Free",
  //   },
  // ],
//   navMain: [
//     {
//       title: "Playground",
//       url: "#",
//       icon: SquareTerminal,
//       isActive: true,
//       items: [
//         {
//           title: "History",
//           url: "#",
//         },
//         {
//           title: "Starred",
//           url: "#",
//         },
//         {
//           title: "Settings",
//           url: "#",
//         },
//       ],
//     },
//     {
//       title: "Models",
//       url: "#",
//       icon: Bot,
//       items: [
//         {
//           title: "Genesis",
//           url: "#",
//         },
//         {
//           title: "Explorer",
//           url: "#",
//         },
//         {
//           title: "Quantum",
//           url: "#",
//         },
//       ],
//     },
//     {
//       title: "Documentation",
//       url: "#",
//       icon: BookOpen,
//       items: [
//         {
//           title: "Introduction",
//           url: "#",
//         },
//         {
//           title: "Get Started",
//           url: "#",
//         },
//         {
//           title: "Tutorials",
//           url: "#",
//         },
//         {
//           title: "Changelog",
//           url: "#",
//         },
//       ],
//     },
//     {
//       title: "Settings",
//       url: "#",
//       icon: Settings2,
//       items: [
//         {
//           title: "General",
//           url: "#",
//         },
//         {
//           title: "Team",
//           url: "#",
//         },
//         {
//           title: "Billing",
//           url: "#",
//         },
//         {
//           title: "Limits",
//           url: "#",
//         },
//       ],
//     },
//   ],
//   projects: [
//     {
//       name: "Design Engineering",
//       url: "#",
//       icon: Frame,
//     },
//     {
//       name: "Sales & Marketing",
//       url: "#",
//       icon: PieChart,
//     },
//     {
//       name: "Travel",
//       url: "#",
//       icon: Map,
//     },
//   ],
}

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
//         label: "Tasks",
//         labelKey: "tasks",
//         href: "/agents/tasks",
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
  // User data will be provided by Clerk authentication
};

const navData = {
  // user: {
  //   name: "shadcn",
  //   email: "m@example.com",
  //   avatar: "/avatars/shadcn.jpg",
  // },
  workspaces: [
    {
      name: "AgentArea",
      logo: GalleryVerticalEnd,
      plan: "Base workspace",
      logoFile: "/starlogo.svg",
    }
  ],
  navMain: [
    {
        title: "Workplace",
        titleKey: "workplace",
        url: "/workplace",
        icon: Home,
    }, {
        title: "Browse",
        titleKey: "browse",
        url: "/agents/browse",
        icon: Bot,
    }, {
        title: "Tasks",
        titleKey: "tasks",
        url: "/tasks",
        icon: ClipboardList,
    }, {
        title: "Connections",
        titleKey: "connections",
        url: "/mcp-servers",
        icon: Plug,
    }, {
      title: "Admin",
      titleKey: "admin",
      url: "#",
      icon: SquareTerminal,
      items: [
        {
            title: "Models",
            titleKey: "providerConfigs",
            url: "/admin/provider-configs",
            icon: Key,
          },
      ],
    },
  ],
}


export default function MainLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <SidebarProvider>
        <div className="flex md:flex-row flex-col h-screen w-screen overflow-hidden bg-white dark:bg-zinc-800"
        // style={{ backgroundImage: "url('/bg.png')", backgroundSize: "cover", backgroundPosition: "right" }}
        >
          {/* <SideBarWrapper
            menuContent={navContent}
            bottomMenuContent={bottomNavContent}
          /> */}
          <AppSidebar data={navData} />
          <Header menuContent={navContent} bottomMenuContent={bottomNavContent} />
          {/* <main className="flex-1 overflow-hidden pb-[10px] md:pt-[10px] pr-[10px] max-md:px-[10px] max-h-screen">
            <div className=" bg-[#fafbfc] dark:bg-zinc-900 rounded-xl h-full border border-zinc-200 dark:border-zinc-700 overflow-y-auto">
              {children}
            </div>
          </main> */}
          <main className="
            flex-1 overflow-hidden  max-h-screen bg-[#fafbfc] dark:bg-zinc-900 h-full overflow-y-auto "
            // bg-[url('/bg-p.svg')] dark:bg-[url('/bg-p-dark.svg')] bg-no-repeat bg-[right_top_10px]
            // bg-[length:90%_auto] sm:bg-[length:60%_auto] md:bg-[length:60%_auto] lg:bg-[length:auto]"
          >
            {/* <div className="bg-[#fafbfc] dark:bg-zinc-900 rounded-xl h-full border border-zinc-200 dark:border-zinc-700 overflow-y-auto"> */}
              {children}
            {/* </div> */}
          </main>
        </div>
      </SidebarProvider>
      <ThemeToggle className="absolute bottom-2 right-2" />
    </>

    // <>
    //   <SidebarProvider>
    //     <AppSidebar data={navData} />
    //     <main>
    //       <SidebarTrigger />
    //       {children}
    //     </main>
    //   </SidebarProvider>
    //   <ThemeToggle className="absolute bottom-2 right-2" />
    // </>
  );
}
