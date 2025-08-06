import { useAuth, useUser } from "./providers";

export const useSession = () => {
  const { isSignedIn, userId, getToken } = useAuth();
  const { user } = useUser();
  
  return {
    data: {
      user: user ? {
        id: userId,
        email: user.emailAddresses[0]?.emailAddress,
        name: user.fullName,
        image: user.imageUrl,
      } : null,
    },
    status: isSignedIn ? "authenticated" : "unauthenticated",
    getToken,
  };
};

export const useAuthStatus = () => {
  const { isSignedIn } = useAuth();
  return {
    isAuthenticated: isSignedIn,
    isLoading: false,
  };
};
