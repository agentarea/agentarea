import "./globals.css";

import { ThemeProvider } from "@/components/providers/theme-provider"
import MainLayout from "@/components/MainLayout";
import { Open_Sans, Montserrat } from "next/font/google";

const openSans = Open_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"] });
const montserrat = Montserrat({subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-montserrat"});


export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${openSans.className} ${montserrat.variable}`}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <MainLayout>
            {children}
          </MainLayout>
        </ThemeProvider>
      </body>
    </html>
  );
}
