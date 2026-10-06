"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";
import { SegmentedControl } from "@/components/ui/segmented-control";

const THEMES = [
  { value: "dark", key: "themeDark", Icon: Moon },
  { value: "light", key: "themeLight", Icon: Sun },
] as const;

type Theme = (typeof THEMES)[number]["value"];

/** Light or dark, stored per device by next-themes. */
export default function ThemeSelect() {
  const t = useTranslations("SettingsPage.preferences");
  const { resolvedTheme, setTheme } = useTheme();
  // The theme in effect is only known in the browser; until then nothing is
  // selected, so the server render and hydration agree.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <SegmentedControl<Theme>
      layoutId="settings-theme"
      value={(mounted ? resolvedTheme : undefined) as Theme}
      onChange={setTheme}
      itemClassName="min-w-[6.5rem]"
      items={THEMES.map(({ value, key, Icon }) => ({
        value,
        label: (
          <span className="flex items-center gap-1.5 whitespace-nowrap">
            <Icon aria-hidden className="h-3.5 w-3.5" strokeWidth={1.8} />
            {t(key)}
          </span>
        ),
      }))}
    />
  );
}
