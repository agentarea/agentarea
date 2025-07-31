"use client";

import { useAuth as useClerkAuth, useUser as useClerkUser } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { AuthHook, User } from "@/types/auth";

/**
 * Custom authentication hook that abstracts the underlying auth provider (currently Clerk)
 * This allows us to easily switch auth providers in the future without changing all components
 */
export function useAuth(): AuthHook {
  const { isLoaded, isSignedIn, signOut: clerkSignOut } = useClerkAuth();
  const { user: clerkUser } = useClerkUser();
  const router = useRouter();

  // Transform Clerk user to our User interface
  const user: User | null = clerkUser ? {
    id: clerkUser.id,
    email: clerkUser.primaryEmailAddress?.emailAddress || '',
    firstName: clerkUser.firstName || undefined,
    lastName: clerkUser.lastName || undefined,
    fullName: clerkUser.fullName || undefined,
    imageUrl: clerkUser.imageUrl || undefined,
    createdAt: clerkUser.createdAt || undefined,
    updatedAt: clerkUser.updatedAt || undefined,
  } : null;

  const signIn = () => {
    router.push('/sign-in');
  };

  const signUp = () => {
    router.push('/sign-up');
  };

  const signOut = async () => {
    await clerkSignOut();
    router.push('/');
  };

  return {
    isLoaded,
    isSignedIn: isSignedIn || false,
    user,
    signIn,
    signOut,
    signUp,
  };
}