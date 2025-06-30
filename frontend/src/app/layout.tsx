import "./globals.css";
import "@copilotkit/react-ui/styles.css";

import { ThemeProvider } from "@/components/providers/theme-provider"
import MainLayout from "@/components/MainLayout";
import { Open_Sans, Montserrat } from "next/font/google";
import {NextIntlClientProvider} from 'next-intl';
import {getLocale} from 'next-intl/server';
import { CopilotKit } from "@copilotkit/react-core";

const openSans = Open_Sans({ subsets: ["latin"], weight: ["300", "400", "500", "600", "700"] });
const montserrat = Montserrat({subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-montserrat"});


export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getLocale(); 
  return (
    <html lang={locale} suppressHydrationWarning>
      <body className={`${openSans.className} ${montserrat.variable}`}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <NextIntlClientProvider>
            <CopilotKit 
              runtimeUrl="/api/copilotkit"
              agent="agentAreaAgent"
              showDevConsole={process.env.NODE_ENV === "development"}
            >
              <MainLayout>
                {children}
              </MainLayout>
            </CopilotKit>
          </NextIntlClientProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
