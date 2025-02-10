import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import SidebarWithState from "@/components/SidebarWithState";

export const metadata: Metadata = {
  title: "AgentMesh",
  description: "Your AI Agent Platform",
};

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased h-screen`}>
        <div className="h-full">
          <SidebarWithState />
          <main className="md:pl-[300px] p-4">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
