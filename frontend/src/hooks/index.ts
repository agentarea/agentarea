// Custom authentication hooks that abstract the underlying auth provider
export { useAuth } from './useAuth';
export { useUser } from './useUser';

// Re-export types for convenience
export type { User, AuthState, AuthActions, AuthHook } from '@/types/auth';

export { useCookie } from './useCookie';
export { useSearchWithDebounce } from './useSearchWithDebounce';
export { useTabState } from './useTabState';
// export { useModelInfo } from './useModelInfo';
// export type { ModelInfo } from './useModelInfo';