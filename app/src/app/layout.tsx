import "./globals.css";
import SidebarWithState from "@/components/SidebarWithState";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { ThemeProvider } from "@/components/providers/theme-provider"

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <div className="flex h-screen overflow-hidden">
            <SidebarWithState />
            <main className="flex-1 overflow-y-auto">
              {children}
            </main>
          </div>
          <ThemeToggle className="absolute bottom-2 right-2"/>
        </ThemeProvider>
      </body>
    </html>
  );
}
