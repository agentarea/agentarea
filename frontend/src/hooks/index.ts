// Custom authentication hooks that abstract the underlying auth provider
export { useAuth } from './useAuth';
export { useUser } from './useUser';

// Re-export types for convenience
export type { User, AuthState, AuthActions, AuthHook } from '@/types/auth';