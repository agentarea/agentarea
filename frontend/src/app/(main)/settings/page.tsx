"use client";

import { useTranslations } from "next-intl";
import { Globe, LogOut, Shield, User as UserIcon } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { useAuth } from "@/hooks/useAuth";
import LanguageSelect from "./components/LanguageSelect";
import ProfileForm from "./components/ProfileForm";

export default function SettingsPage() {
  const t = useTranslations("SettingsPage");
  const { user, isLoaded, signOut } = useAuth();

  // Compact Loading state
  if (!isLoaded) {
    return <LoadingSpinner fullScreen={true} />;
  }

  // Transform user data for ProfileForm component
  const userForProfile = user
    ? {
        name: user.name || user.email || "User",
        email: user.email || "",
        avatar: user.image || "https://github.com/shadcn.png",
      }
    : null;

  const handleLogout = async () => {
    await signOut();
  };

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
        controls: (
          <Button
            onClick={handleLogout}
            variant="outline"
            size="sm"
            className="gap-1"
          >
            <LogOut className="h-3 w-3" />
            {t("logout")}
          </Button>
        ),
      }}
    >
      {/* Compact Main Content */}
      <div className="mx-auto max-w-4xl">
        <div className="space-y-4">
          {/* Compact Profile Section */}
          <section id="profile" className="card p-0">
            <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-medium text-gray-900 dark:text-white">
                    {t("profile.title")}
                  </h2>
                  <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                    {t("profile.description")}
                  </p>
                </div>
                <div className="flex items-center gap-1 rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
                  <Shield className="h-2.5 w-2.5" />
                  Auth Provider Managed
                </div>
              </div>
            </div>
            <div className="p-4">
              {userForProfile ? (
                <ProfileForm {...userForProfile} />
              ) : (
                <div className="py-6 text-center">
                  <UserIcon className="mx-auto mb-2 h-8 w-8 text-gray-400" />
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    No user data available
                  </p>
                </div>
              )}
            </div>
          </section>

          {/* Compact Preferences Section */}
          <section id="preferences" className="card p-0">
            <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
              <h2 className="text-base font-medium text-gray-900 dark:text-white">
                {t("preferences.title")}
              </h2>
              <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                {t("preferences.description")}
              </p>
            </div>
            <div className="space-y-3 p-4">
              {/* Compact Language Setting */}
              <div className="flex items-center justify-between border-b border-gray-100 py-2 last:border-0 dark:border-gray-700">
                <div className="flex-1">
                  <h3 className="text-sm font-medium text-gray-900 dark:text-white">
                    {t("preferences.language")}
                  </h3>
                  <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                    {t("preferences.languageDescription")}
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
                    {t("preferences.theme")}
                  </h3>
                  <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                    {t("preferences.themeDescription")}
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
    </ContentBlock>
  );
}
