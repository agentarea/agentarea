import "./globals.css";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { Inter } from "next/font/google";
import { cookies } from "next/headers";
import { SessionProvider } from "@ory/elements-react/client";
import { getServerSession } from "@ory/nextjs/app";
import ConditionalLayout from "@/components/ConditionalLayout";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { Toaster } from "@/components/ui/sonner";

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
  variable: "--font-inter",
  preload: true,
});

// Runtime config to inject into window.__ENV__ for client-side access
// This avoids the need for NEXT_PUBLIC_* env vars which are bundled at build time
function getRuntimeConfig() {
  return {
    CLIENT_ORY_SDK_URL: process.env.ORY_SDK_URL || "",
  };
}

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
  const runtimeConfig = getRuntimeConfig();

  return (
    <html lang={locale} suppressHydrationWarning className={inter.variable}>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `window.__ENV__ = ${JSON.stringify(runtimeConfig)};`,
          }}
        />
      </head>
      <body className={inter.className}>
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
