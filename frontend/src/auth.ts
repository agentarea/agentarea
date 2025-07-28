// Re-export Clerk components and hooks for convenience
export {
  ClerkProvider,
  SignInButton,
  SignOutButton,
  useAuth,
  useUser,
  SignedIn,
  SignedOut,
  RedirectToSignIn,
  SignIn,
  SignUp,
  UserButton
} from '@clerk/nextjs'

// Session helper for compatibility
export const getSession = () => {
  // This is a placeholder - in a real implementation, you would use Clerk's useAuth hook
  // The actual session management is handled by Clerk internally
  return null
}