import { SidebarProvider } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import SettingsSidebar from "./SettingsSidebar";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <SidebarProvider defaultOpen={true}>
        <div className="flex h-screen w-screen flex-row overflow-hidden bg-layoutBackground py-2 pr-2 pl-2 md:pl-0">
          <SettingsSidebar />
          <main className="flex-1 rounded-sm overflow-hidden max-h-screen bg-white dark:bg-zinc-800 h-full overflow-y-auto border border-sidebar-border">
            {children}
          </main>
        </div>
      </SidebarProvider>
      <ThemeToggle className="fixed bottom-2 right-2 z-50" />
    </>
  );
}
