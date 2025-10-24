export interface User {
  id: string;
  email?: string;
  firstName?: string;
  lastName?: string;
  fullName?: string;
  imageUrl?: string;
  createdAt?: Date;
  updatedAt?: Date;
}

export interface AuthState {
  isLoaded: boolean;
  isSignedIn: boolean;
  user: User | null;
}

export interface AuthActions {
  signIn: () => void;
  signOut: () => Promise<void>;
  signUp: () => void;
}

export type AuthHook = AuthState & AuthActions;
