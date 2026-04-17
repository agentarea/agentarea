import type { Metadata } from "next";
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

export const metadata: Metadata = {
  metadataBase: new URL('https://app.agentarea.ai/'),
  title: {
    default: "AgentArea",
    template: "%s | AgentArea",
  },
  description: "Connect intelligent agents securely with privacy at the core. Our platform ensures data protection while enabling seamless agent collaboration.",
  openGraph: {
    title: "AgentArea - Privacy-First Agent Platform",
    description: "Connect intelligent agents securely with privacy at the core. Our platform ensures data protection while enabling seamless agent collaboration.",
    locale: 'en_US',
    type: 'website',
    siteName: 'AgentArea',
    images: [
      {
        url: '/cover.png',
        width: 1308,
        height: 650,
        alt: 'AgentArea - Privacy-First Agent Platform'
      }
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'AgentArea - Privacy-First Agent Platform',
    description: "Connect intelligent agents securely with privacy at the core. Our platform ensures data protection while enabling seamless agent collaboration.",
    images: ['/cover.png'],
  },
  other: {
    'vk:image': '/cover.png',
    'og:image': '/cover.png',
    'og:image:alt': 'AgentArea - Privacy-First Agent Platform',
  }
};

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
  variable: "--font-inter",
  preload: true,
});

// Runtime config to inject into window.__ENV__ for client-side access
// Uses ORY_BROWSER_URL (not NEXT_PUBLIC_*) to avoid Next.js build-time inlining
function getRuntimeConfig() {
  return {
    CLIENT_ORY_SDK_URL: process.env.ORY_BROWSER_URL || process.env.ORY_SDK_URL || "",
    CLIENT_API_URL: process.env.API_BROWSER_URL || process.env.API_URL || "http://localhost:8000",
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
