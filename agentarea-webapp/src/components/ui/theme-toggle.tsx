"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

interface ThemeToggleProps {
  className?: string;
}

export function ThemeToggle({ className }: ThemeToggleProps) {
  const t = useTranslations("Common");
  const [mounted, setMounted] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  useEffect(() => {
    setMounted(true);
  }, []);

  // Не рендерим компонент до монтирования, чтобы избежать проблем с гидратацией
  if (!mounted) {
    return null;
  }

  return (
    <button
      type="button"
      aria-label={t(isDark ? "switchToLightTheme" : "switchToDarkTheme")}
      className={cn(
        "flex h-8 w-16 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background max-[767px]:h-11",
        className
      )}
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      <span
        aria-hidden="true"
        className={cn(
          "flex h-8 w-16 items-center justify-between rounded-full p-1 transition-colors duration-300",
          isDark
            ? "border border-zinc-800 bg-zinc-950"
            : "border border-zinc-200 bg-white"
        )}
      >
        <span
          className={cn(
            "flex h-6 w-6 items-center justify-center rounded-full transition-transform duration-300",
            isDark
              ? "translate-x-0 transform bg-zinc-800"
              : "translate-x-8 transform bg-gray-200"
          )}
        >
          {isDark ? (
            <Moon className="h-4 w-4 text-white" strokeWidth={1.5} />
          ) : (
            <Sun className="h-4 w-4 text-gray-700" strokeWidth={1.5} />
          )}
        </span>
        <span
          className={cn(
            "flex h-6 w-6 items-center justify-center rounded-full transition-transform duration-300",
            isDark ? "bg-transparent" : "-translate-x-8 transform"
          )}
        >
          {isDark ? (
            <Sun className="h-4 w-4 text-gray-500" strokeWidth={1.5} />
          ) : (
            <Moon className="h-4 w-4 text-black" strokeWidth={1.5} />
          )}
        </span>
      </span>
    </button>
  );
}
