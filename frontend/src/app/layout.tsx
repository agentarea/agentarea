import "./globals.css";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { Montserrat, Open_Sans } from "next/font/google";
import { cookies } from "next/headers";
import { SessionProvider } from "@ory/elements-react/client";
import { getServerSession } from "@ory/nextjs/app";
import ConditionalLayout from "@/components/ConditionalLayout";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { Toaster } from "@/components/ui/sonner";

const openSans = Open_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});
const montserrat = Montserrat({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-montserrat",
});

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getLocale();
  const cookieStore = await cookies();
  const sidebarCookie = cookieStore.get("sidebar_state")?.value;
  const sidebarDefaultOpen =
    sidebarCookie !== undefined ? sidebarCookie === "true" : true;
  const session = await getServerSession();

  return (
    <html lang={locale} suppressHydrationWarning>
      <body className={`${openSans.className} ${montserrat.variable}`}>
        <SessionProvider session={session}>
          <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
            <NextIntlClientProvider>
              <ConditionalLayout sidebarDefaultOpen={sidebarDefaultOpen}>
                {children}
              </ConditionalLayout>
            </NextIntlClientProvider>
          </ThemeProvider>
        </SessionProvider>
        <Toaster />
      </body>
    </html>
  );
}
