"use client";

import { User } from "@/types/auth";
import { useAuth } from "./useAuth";

/**
 * Hook to get current user data
 * Returns user object or null if not authenticated
 */
export function useUser(): { user: User | null; isLoaded: boolean } {
  const { user, isLoaded } = useAuth();

  return {
    user,
    isLoaded,
  };
}
