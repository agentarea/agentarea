"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

const THEMES = [
  { value: "system", key: "themeSystem", Icon: Monitor },
  { value: "light", key: "themeLight", Icon: Sun },
  { value: "dark", key: "themeDark", Icon: Moon },
] as const;

/** The account menu's theme row: system, light or dark, stored per device. */
export function ThemeSwitch() {
  const t = useTranslations("NavUser");
  const { theme, setTheme } = useTheme();
  // The stored theme is only known in the browser; until then nothing is
  // selected, so the server render and hydration agree.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <div className="flex items-center justify-between gap-3 px-2 py-1.5 text-sm">
      <span>{t("theme")}</span>
      <div
        role="radiogroup"
        aria-label={t("theme")}
        className="flex items-center rounded-full border border-border p-0.5"
      >
        {THEMES.map(({ value, key, Icon }) => {
          const selected = mounted && theme === value;
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={t(key)}
              title={t(key)}
              onClick={() => setTheme(value)}
              className={cn(
                "flex size-6 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selected && "bg-muted text-foreground"
              )}
            >
              <Icon className="size-3.5" strokeWidth={1.8} />
            </button>
          );
        })}
      </div>
    </div>
  );
}
