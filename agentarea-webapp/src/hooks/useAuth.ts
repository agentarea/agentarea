"use client";

import { useSession } from "@ory/elements-react/client";
import { displayName } from "@/lib/display-name";

interface User {
  id: string;
  name?: string;
  email?: string;
  image?: string;
}

interface AuthState {
  user: User | null;
  isLoaded: boolean;
  isSignedIn: boolean;
  signOut: () => void;
}

export function useAuth(): AuthState {
  const { session, isLoading } = useSession();

  const user = session?.identity
    ? {
        id: session.identity.id,
        name: displayName(session.identity.traits),
        email: session.identity.traits?.email,
      }
    : null;

  const signOut = () => {
    window.location.href = "/auth/logout";
  };

  return {
    user,
    isLoaded: !isLoading,
    isSignedIn: !!session?.identity,
    signOut,
  };
}
