"use client";

import { useSession } from "@ory/elements-react/client";

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
        name: session.identity.traits?.name?.first
          ? `${session.identity.traits.name.first} ${session.identity.traits.name.last || ""}`.trim()
          : session.identity.traits?.username || session.identity.traits?.email,
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
