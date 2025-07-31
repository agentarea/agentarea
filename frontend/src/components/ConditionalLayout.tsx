"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import MainLayout from "@/components/MainLayout";

interface ConditionalLayoutProps {
  children: React.ReactNode;
}

// Routes that should NOT use the main layout (auth pages, etc.)
const NO_LAYOUT_ROUTES = [
  '/sign-in',
  '/sign-up', 
];

// Known protected routes that should use main layout when authenticated
const PROTECTED_ROUTES = [
  '/agents',
  '/mcp-servers',
  '/tasks',
  '/workplace',
  '/dashboard',
  '/admin',
  '/settings',
  '/chat',
  '/home',
];

export default function ConditionalLayout({ children }: ConditionalLayoutProps) {
  const pathname = usePathname();
  const { isSignedIn, isLoaded } = useAuth();
  
  // Always skip layout for auth pages
  const shouldUseNoLayout = NO_LAYOUT_ROUTES.some(route => 
    pathname.startsWith(route)
  );
  
  if (shouldUseNoLayout) {
    return <>{children}</>;
  }
  
  // For unknown routes: only use main layout if user is authenticated
  const isKnownRoute = PROTECTED_ROUTES.some(route => pathname.startsWith(route)) || pathname === '/';
  
  if (!isKnownRoute && isLoaded && !isSignedIn) {
    // Unknown route + unauthenticated = no layout (clean 404)
    return <>{children}</>;
  }
  
  // Use MainLayout for known routes or authenticated users
  return <MainLayout>{children}</MainLayout>;
}