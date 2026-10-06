import { getTranslations } from "next-intl/server";
import { Skeleton } from "@/components/ui/skeleton";
import SettingsRow from "./SettingsRow";
import { SettingsFooter, SettingsSection } from "./SettingsSection";

const PROFILE_FIELDS = ["email", "firstName", "lastName", "username"] as const;

/**
 * The settings page while its Kratos flow loads: the same sections, titles and
 * rows, with placeholders where the values and controls go. The workspace
 * section is left out — only admins see it, and it would vanish for the rest.
 */
export default async function SettingsSkeleton() {
  const t = await getTranslations("SettingsPage");

  return (
    <>
      <SettingsSection title={t("profile.personalInfo")}>
        <div className="flex items-center gap-3 border-b border-border/60 bg-muted/20 px-4 py-3.5">
          <Skeleton className="h-11 w-11 rounded-[13px]" />
          <div className="space-y-1.5">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-3 w-16" />
          </div>
        </div>
        {PROFILE_FIELDS.map((field) => (
          <SettingsRow
            key={field}
            title={t(`profile.${field}`)}
            description={field === "email" ? t("profile.emailHint") : undefined}
            control="field"
          >
            <Skeleton className="h-9 w-full" />
          </SettingsRow>
        ))}
        <SettingsFooter status={<Skeleton className="h-3 w-32" />}>
          <Skeleton className="h-8 w-24" />
        </SettingsFooter>
      </SettingsSection>

      <SettingsSection title={t("security.title")}>
        <SettingsRow
          title={t("security.password")}
          description={t("security.passwordDescription")}
        >
          <Skeleton className="h-8 w-32" />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title={t("accounts.title")}
        description={t("accounts.description")}
      >
        {[0, 1].map((row) => (
          <SettingsRow
            key={row}
            tile={<Skeleton className="h-8 w-8 rounded-[9px]" />}
            title={<Skeleton className="h-4 w-20" />}
            description={<Skeleton className="mt-1 h-3 w-24" />}
          >
            <Skeleton className="h-8 w-24" />
          </SettingsRow>
        ))}
      </SettingsSection>

      <SettingsSection title={t("preferences.title")}>
        <SettingsRow
          title={t("preferences.language")}
          description={t("preferences.languageDescription")}
        >
          <Skeleton className="h-8 w-40" />
        </SettingsRow>
        <SettingsRow
          title={t("preferences.theme")}
          description={t("preferences.themeDescription")}
        >
          <Skeleton className="h-8 w-[13.5rem]" />
        </SettingsRow>
      </SettingsSection>
    </>
  );
}
