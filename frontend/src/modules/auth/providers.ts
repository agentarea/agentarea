import { 
  ClerkProvider, 
  SignInButton, 
  SignOutButton, 
  useAuth as useClerkAuth,
  useUser as useClerkUser,
  SignedIn,
  SignedOut,
  RedirectToSignIn
} from "@clerk/nextjs";

// Re-export Clerk components
export {
  ClerkProvider,
  SignInButton,
  SignOutButton,
  useClerkAuth as useAuth,
  useClerkUser as useUser,
  SignedIn,
  SignedOut,
  RedirectToSignIn
};

// Helper functions for backward compatibility
export const signIn = SignInButton;
export const signOut = SignOutButton;

// Session helper
export const getSession = () => {
  const { isSignedIn, userId, getToken } = useClerkAuth();
  const { user } = useClerkUser();
  
  return {
    user: user ? {
      id: userId,
      email: user.emailAddresses[0]?.emailAddress,
      name: user.fullName,
      image: user.imageUrl,
    } : null,
    isAuthenticated: isSignedIn,
    getToken
  };
};
