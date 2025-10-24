"use client";

import { usePathname } from "next/navigation";
import AuthGuard from "@/components/auth/AuthGuard";
import MainLayout from "@/components/MainLayout";
import { useAuth } from "@/hooks/useAuth";

interface ConditionalLayoutProps {
  children: React.ReactNode;
  sidebarDefaultOpen?: boolean;
}

// Routes that should NOT use the main layout (auth pages, etc.)
const NO_LAYOUT_ROUTES = [
  "/auth/login",
  "/auth/logout",
  "/auth/registration",
  "/auth/consent",
  "/auth/verification",
  "/auth/recovery",
  "/auth/error",
];

// Known protected routes that should use main layout when authenticated
const PROTECTED_ROUTES = [
  "/agents",
  "/mcp-servers",
  "/tasks",
  "/workplace",
  "/dashboard",
  "/admin",
  "/settings",
  "/chat",
  "/home",
];

export default function ConditionalLayout({
  children,
  sidebarDefaultOpen,
}: ConditionalLayoutProps) {
  const pathname = usePathname();
  const { isSignedIn, isLoaded } = useAuth();

  // Always skip layout for auth pages and root page
  const shouldUseNoLayout =
    NO_LAYOUT_ROUTES.some((route) => pathname.startsWith(route)) ||
    pathname === "/";

  if (shouldUseNoLayout) {
    return <>{children}</>;
  }

  // For unknown routes: only use main layout if user is authenticated
  const isKnownRoute = PROTECTED_ROUTES.some((route) =>
    pathname.startsWith(route)
  );

  if (!isKnownRoute && isLoaded && !isSignedIn) {
    // Unknown route + unauthenticated = no layout (clean 404)
    return <>{children}</>;
  }

  // Use MainLayout for known protected routes
  return (
    <AuthGuard>
      <MainLayout sidebarDefaultOpen={sidebarDefaultOpen}>
        {children}
      </MainLayout>
    </AuthGuard>
  );
}
