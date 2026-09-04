import type { Metadata } from "next";
import "./globals.css";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { Inter } from "next/font/google";
import { cookies, headers } from "next/headers";
import { SessionProvider } from "@ory/elements-react/client";
import { getServerSession } from "@ory/nextjs/app";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import ConditionalLayout from "@/components/ConditionalLayout";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { getWorkspaceContext } from "@/lib/workspace-context";

const sharedMetadata: Omit<Metadata, "metadataBase"> = {
  title: {
    default: "AgentArea",
    template: "%s | AgentArea",
  },
  description:
    "Connect intelligent agents securely with privacy at the core. Our platform ensures data protection while enabling seamless agent collaboration.",
  openGraph: {
    title: "AgentArea - Privacy-First Agent Platform",
    description:
      "Connect intelligent agents securely with privacy at the core. Our platform ensures data protection while enabling seamless agent collaboration.",
    locale: "en_US",
    type: "website",
    siteName: "AgentArea",
    images: [
      {
        url: "/cover.png",
        width: 1308,
        height: 650,
        alt: "AgentArea - Privacy-First Agent Platform",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "AgentArea - Privacy-First Agent Platform",
    description:
      "Connect intelligent agents securely with privacy at the core. Our platform ensures data protection while enabling seamless agent collaboration.",
    images: ["/cover.png"],
  },
  other: {
    "vk:image": "/cover.png",
    "og:image": "/cover.png",
    "og:image:alt": "AgentArea - Privacy-First Agent Platform",
  },
};

function getMetadataFallbackBase() {
  return (
    process.env.NEXT_PUBLIC_APP_URL ||
    process.env.APP_URL ||
    "https://app.agentarea.ai/"
  );
}

async function getMetadataBase() {
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") || requestHeaders.get("host");

  if (!host) {
    return new URL(getMetadataFallbackBase());
  }

  const protocol = requestHeaders.get("x-forwarded-proto") || "https";
  return new URL(`${protocol}://${host}`);
}

export async function generateMetadata(): Promise<Metadata> {
  return {
    metadataBase: await getMetadataBase(),
    ...sharedMetadata,
  };
}

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
  // Anonymous visitors (landing, auth) have no workspaces to switch between,
  // and listing them would provision a personal workspace for nobody.
  const { workspaces, active } = session
    ? await getWorkspaceContext()
    : { workspaces: [], active: null };

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
              <NuqsAdapter>
                <ConditionalLayout
                  sidebarDefaultOpen={sidebarDefaultOpen}
                  workspaces={workspaces}
                  activeWorkspaceSlug={active?.slug ?? null}
                >
                  {children}
                </ConditionalLayout>
              </NuqsAdapter>
            </NextIntlClientProvider>
          </ThemeProvider>
        </SessionProvider>
        <Toaster />
      </body>
    </html>
  );
}
