"use client";

import { useTranslations } from "next-intl";
import { Globe, LogOut, Moon, Shield, User as UserIcon } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import LanguageSelect from "./components/LanguageSelect";
import ProfileForm from "./components/ProfileForm";

export default function SettingsClient() {
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
      }
    : null;

  const handleLogout = async () => {
    await signOut();
  };

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }, {label: t("profile.title")}],
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
          <section id="profile" className="border-0 p-0">
            <div className="px-4">
              <div className="flex items-center justify-between">
                <div></div>
                <div className="flex items-center gap-1 rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
                  <Shield className="h-2.5 w-2.5" />
                  Auth Provider Managed
                </div>
              </div>
            </div>
            <div className="px-4 pb-4">
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
          <section id="preferences" className="border-0 p-0">
            <div className="px-4 py-3">
              <h2 className="text-base font-medium text-gray-900 dark:text-white">
                {t("preferences.title")}
              </h2>
              <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
                {t("preferences.description")}
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 p-4">
              {/* Language Setting */}
              <div
                className={cn(
                  "group relative flex items-start gap-3 w-full p-4",
                  "bg-white dark:bg-zinc-900",
                  "border border-zinc-200/60 dark:border-zinc-800",
                  "rounded-md transition-all duration-300 ease-out",
                  "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)]",
                  "relative overflow-hidden"
                )}
              >
                <div
                  className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03] pointer-events-none"
                  style={{
                    backgroundImage: `repeating-linear-gradient(
                       -45deg,
                       currentColor,
                       currentColor 1px,
                       transparent 1px,
                       transparent 10px
                     )`,
                  }}
                />
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10 z-10">
                  <Globe className="h-4 w-4" />
                </div>

                <div className="flex flex-col gap-0.5 flex-1 min-w-0 z-10">
                  <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                    {t("preferences.language")}
                  </span>
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    {t("preferences.languageDescription")}
                  </span>
                </div>

                <div className="shrink-0 z-10">
                  <LanguageSelect />
                </div>
              </div>

              {/* Theme Setting */}
              <div
                className={cn(
                  "group relative flex items-start gap-3 w-full p-4",
                  "bg-white dark:bg-zinc-900",
                  "border border-zinc-200/60 dark:border-zinc-800",
                  "rounded-md transition-all duration-300 ease-out",
                  "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)]",
                  "relative overflow-hidden"
                )}
              >
                <div
                  className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03] pointer-events-none"
                  style={{
                    backgroundImage: `repeating-linear-gradient(
                       -45deg,
                       currentColor,
                       currentColor 1px,
                       transparent 1px,
                       transparent 10px
                     )`,
                  }}
                />
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10 z-10">
                  <Moon className="h-4 w-4" />
                </div>

                <div className="flex flex-col gap-0.5 flex-1 min-w-0 z-10">
                  <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                    {t("preferences.theme")}
                  </span>
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    {t("preferences.themeDescription")}
                  </span>
                </div>

                <div className="shrink-0 z-10">
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
