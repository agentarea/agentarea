import {
  Bot,
  Brain,
  ClipboardList,
  FolderKanban,
  GalleryVerticalEnd,
  Home,
  Inbox,
  Key,
  LucideProps,
  Network,
  Plug,
  Sparkles,
  SquareTerminal,
  Zap,
} from "lucide-react";
import { SidebarProvider } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/ui/theme-toggle";
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

export default function MainLayout({
  children,
  sidebarDefaultOpen = true,
}: {
  children: React.ReactNode;
  sidebarDefaultOpen?: boolean;
}) {
  return (
    <>
      <SidebarProvider defaultOpen={sidebarDefaultOpen}>
        <div className="flex h-screen w-screen flex-row overflow-hidden bg-layoutBackground py-2 pr-2 pl-2 md:pl-0">
          <AppSidebar data={navData} />
          {/* <main className="bg-size-100 h-full max-h-screen flex-1 overflow-hidden overflow-y-auto bg-[url('/dots3.png')] bg-contain bg-repeat dark:bg-zinc-900 dark:bg-none"> */}
            <main className="flex-1 rounded-sm overflow-hidden  max-h-screen bg-white dark:bg-zinc-800 h-full overflow-y-auto border border-sidebar-border">
            {children}
          </main>
        </div>
      </SidebarProvider>
      <ThemeToggle className="fixed bottom-2 right-2 z-50" />
    </>
  );
}
