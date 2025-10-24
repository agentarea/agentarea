import {
  Bot,
  ClipboardList,
  GalleryVerticalEnd,
  Home,
  Key,
  LucideProps,
  Plug,
  SquareTerminal,
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
  navMain: [
    {
      title: "Workplace",
      titleKey: "workplace",
      url: "/workplace",
      icon: Home,
    },
    {
      title: "Browse",
      titleKey: "browse",
      url: "/agents",
      icon: Bot,
    },
    {
      title: "Tasks",
      titleKey: "tasks",
      url: "/tasks",
      icon: ClipboardList,
    },
    {
      title: "Connections",
      titleKey: "connections",
      url: "/mcp-servers",
      icon: Plug,
    },
    {
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
        <div className="flex h-screen w-screen flex-col overflow-hidden bg-white dark:bg-zinc-800 md:flex-row">
          <AppSidebar data={navData} />
          <main className="bg-size-100 h-full max-h-screen flex-1 overflow-hidden overflow-y-auto bg-[url('/dots3.png')] bg-contain bg-repeat dark:bg-zinc-900 dark:bg-none">
            {/* <main className="flex-1 overflow-hidden  max-h-screen bg-[#fafbfc] dark:bg-zinc-900 h-full overflow-y-auto "> */}
            {children}
          </main>
        </div>
      </SidebarProvider>
      <ThemeToggle className="absolute bottom-2 right-2" />
    </>
  );
}
