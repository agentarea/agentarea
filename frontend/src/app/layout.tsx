import "./globals.css";

import { ClerkProvider } from "@clerk/nextjs";
import { ThemeProvider } from "@/components/providers/theme-provider";
import ConditionalLayout from "@/components/ConditionalLayout";
import { Toaster } from "@/components/ui/sonner";
import { Open_Sans, Montserrat } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";

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
  return (
    <html lang={locale} suppressHydrationWarning>
      <body className={`${openSans.className} ${montserrat.variable}`}>
        <ClerkProvider
          appearance={{
            elements: {
              formButtonPrimary: 
                "bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-md transition duration-200",
              card: "bg-white dark:bg-gray-800 shadow-none",
              headerTitle: "text-gray-900 dark:text-white",
              headerSubtitle: "text-gray-600 dark:text-gray-400",
              socialButtonsBlockButton: 
                "border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700",
              dividerLine: "bg-gray-300 dark:bg-gray-600",
              dividerText: "text-gray-500 dark:text-gray-400",
              formFieldInput: 
                "border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white",
              formFieldLabel: "text-gray-700 dark:text-gray-300",
              footerActionLink: "text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300",
            },
          }}
        >
          <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
            <NextIntlClientProvider>
              <ConditionalLayout>{children}</ConditionalLayout>
            </NextIntlClientProvider>
          </ThemeProvider>
          <Toaster />
        </ClerkProvider>
      </body>
    </html>
  );
}
