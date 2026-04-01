import { SidebarProvider } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { navData } from "@/lib/nav-data";
import { AppSidebar } from "./components/AppSidebar";

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
          <main className="flex-1 rounded-sm overflow-hidden  max-h-screen bg-white dark:bg-zinc-800 h-full overflow-y-auto border border-sidebar-border">
            {children}
          </main>
        </div>
      </SidebarProvider>
      <ThemeToggle className="fixed bottom-2 right-2 z-50" />
    </>
  );
}
