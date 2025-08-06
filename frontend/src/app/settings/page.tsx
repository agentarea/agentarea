"use client";

import { useTranslations } from 'next-intl';
import { User as UserIcon, Globe, LogOut, Shield } from 'lucide-react';
import { ThemeToggle } from "@/components/ui/theme-toggle";
import LanguageSelect from './components/LanguageSelect';
import ProfileForm from './components/ProfileForm';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/hooks/useAuth';

export default function SettingsPage() {
    const t = useTranslations('SettingsPage');
    const { user, isLoaded, signOut } = useAuth();

    // Compact Loading state
    if (!isLoaded) {
        return (
            <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
                <div className="max-w-6xl mx-auto px-4 py-4">
                    <div className="flex items-center justify-center py-8">
                        <div className="text-center">
                            <div className="inline-block animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-blue-500"></div>
                            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">Loading...</p>
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    // Transform user data for ProfileForm component
    const userForProfile = user ? {
        name: user.fullName || `${user.firstName || ''} ${user.lastName || ''}`.trim() || user.email,
        email: user.email,
        avatar: user.imageUrl || 'https://github.com/shadcn.png'
    } : null;

    const handleLogout = async () => {
        await signOut();
    };

    return (
        <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
            {/* Compact Header */}
            <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                <div className="max-w-6xl mx-auto px-4 py-4">
                    <div className="flex items-center justify-between">
                        <div>
                            <h1 className="text-xl font-semibold text-gray-900 dark:text-white">
                                {t('title')}
                            </h1>
                            <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                                Manage your account settings and preferences
                            </p>
                        </div>
                        <Button onClick={handleLogout} variant="outline" size="sm" className="gap-1">
                            <LogOut className="w-3 h-3" />
                            {t('logout')}
                        </Button>
                    </div>
                </div>
            </div>

            {/* Compact Main Content */}
            <div className="max-w-4xl mx-auto px-4 py-4">
                <div className="space-y-4">
                        {/* Compact Profile Section */}
                        <section id="profile" className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h2 className="text-base font-medium text-gray-900 dark:text-white">
                                            {t('profile.title')}
                                        </h2>
                                        <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                                            {t('profile.description')}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-1 px-2 py-1 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 rounded-full text-xs font-medium">
                                        <Shield className="w-2.5 h-2.5" />
                                        Auth Provider Managed
                                    </div>
                                </div>
                            </div>
                            <div className="p-4">
                                {userForProfile ? (
                                    <ProfileForm {...userForProfile} />
                                ) : (
                                    <div className="text-center py-6">
                                        <UserIcon className="w-8 h-8 text-gray-400 mx-auto mb-2" />
                                        <p className="text-sm text-gray-500 dark:text-gray-400">No user data available</p>
                                    </div>
                                )}
                            </div>
                        </section>

                        {/* Compact Preferences Section */}
                        <section id="preferences" className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
                                <h2 className="text-base font-medium text-gray-900 dark:text-white">
                                    {t('preferences.title')}
                                </h2>
                                <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                                    {t('preferences.description')}
                                </p>
                            </div>
                            <div className="p-4 space-y-3">
                                {/* Compact Language Setting */}
                                <div className="flex items-center justify-between py-2 border-b border-gray-100 dark:border-gray-700 last:border-0">
                                    <div className="flex-1">
                                        <h3 className="text-sm font-medium text-gray-900 dark:text-white">
                                            {t('preferences.language')}
                                        </h3>
                                        <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                                            {t('preferences.languageDescription')}
                                        </p>
                                    </div>
                                    <div className="ml-4">
                                        <LanguageSelect />
                                    </div>
                                </div>

                                {/* Compact Theme Setting */}
                                <div className="flex items-center justify-between py-2">
                                    <div className="flex-1">
                                        <h3 className="text-sm font-medium text-gray-900 dark:text-white">
                                            {t('preferences.theme')}
                                        </h3>
                                        <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                                            {t('preferences.themeDescription')}
                                        </p>
                                    </div>
                                    <div className="ml-4">
                                        <ThemeToggle />
                                    </div>
                                </div>
                            </div>
                        </section>
                </div>
            </div>
        </div>
    )
}