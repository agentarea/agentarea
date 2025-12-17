import React, {createContext, useContext} from 'react';
import {type AuthState} from '../hooks/useAuth.js';
import {type AuthToken, type User} from '../types/index.js';

export interface AuthContextType extends AuthState {
	login: (
		email: string,
		password: string,
	) => Promise<{
		success: boolean;
		user?: User;
		token?: AuthToken;
		error?: string;
	}>;
	logout: () => Promise<{success: boolean; error?: string}>;
	refreshToken: () => Promise<{
		success: boolean;
		token?: AuthToken;
		error?: string;
	}>;
	clearError: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export interface AuthProviderProps {
	children: React.ReactNode;
	value: AuthContextType;
}

export function AuthProvider({children, value}: AuthProviderProps) {
	return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthContext(): AuthContextType {
	const context = useContext(AuthContext);

	if (!context) {
		throw new Error('useAuthContext must be used within AuthProvider');
	}

	return context;
}
