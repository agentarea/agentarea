"use client";

import { useEffect } from "react";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useAuth } from "@/hooks/useAuth";

interface AuthGuardProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export default function AuthGuard({ children, fallback }: AuthGuardProps) {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useWorkspaceRouter();

  useEffect(() => {
    if (isLoaded && !isSignedIn) {
      router.push("/auth/login");
    }
  }, [isLoaded, isSignedIn, router]);

  if (!isLoaded && !isSignedIn) {
    return fallback || <LoadingSpinner fullScreen={true} />;
  }

  if (!isSignedIn) {
    return (
      fallback || (
        <div className="flex min-h-screen items-center justify-center">
          <div className="text-center">
            <p className="text-gray-600 dark:text-gray-400">
              Redirecting to sign in...
            </p>
          </div>
        </div>
      )
    );
  }

  return <>{children}</>;
}
