"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type ChatWelcomeVariant = "accent" | "neutral";
type ChatWelcomeSize = "sm" | "md";

interface ChatWelcomeProps {
  icon?: LucideIcon;
  title: ReactNode;
  subtitle?: ReactNode;
  variant?: ChatWelcomeVariant; // accent (Workplace, по умолчанию) | neutral (tasks/agents)
  size?: ChatWelcomeSize; // sm | md
  animate?: boolean; // микроподсказки: прыжок и т.д.
  className?: string;
  iconWrapperClassName?: string;
  iconColorClassName?: string; // кастомный цвет иконки
  titleClassName?: string;
  subtitleClassName?: string;
}

export function ChatWelcome({
  icon: Icon,
  title,
  subtitle,
  variant = "accent",
  size = "md",
  animate,
  className,
  iconWrapperClassName,
  iconColorClassName,
  titleClassName,
  subtitleClassName,
}: ChatWelcomeProps) {
  const effectiveAnimate = animate ?? variant === "accent";
  const showIcon = Boolean(Icon);

  const iconWrapperBase =
    variant === "accent"
      ? "bg-primary/5 dark:bg-primary/10"
      : "bg-muted/40 dark:bg-muted/20";
  // В нейтральном варианте возвращаем цветность иконке (требование 2),
  // но держим фон спокойным.
  const iconClass = cn(
    variant === "accent" ? "text-primary opacity-80" : "text-primary",
    iconColorClassName
  );

  const titleBase =
    variant === "accent"
      ? "text-xl sm:text-2xl font-light tracking-tight text-zinc-500 dark:text-zinc-400"
      : "text-lg sm:text-xl font-light tracking-tight text-muted-foreground";

  const sizeClass = size === "sm" ? "space-y-3" : "space-y-4";
  const iconWrapperSize = size === "sm" ? "p-1.5" : "p-2";
  const iconSize = size === "sm" ? "w-4 h-4" : "w-5 h-5";

  return (
    <div
      className={cn(
        "relative flex flex-col items-center justify-center text-center max-w-2xl px-4",
        variant === "accent"
          ? "animate-in fade-in zoom-in duration-1000 slide-in-from-bottom-2"
          : "animate-in fade-in duration-500",
        sizeClass,
        className
      )}
    >
      <div className="relative z-10 flex flex-col items-center gap-3">
        {showIcon && (
          <div
            className={cn(
              "rounded-sm mb-1",
              iconWrapperSize,
              iconWrapperBase,
              effectiveAnimate && "animate-bounce-slow",
              iconWrapperClassName
            )}
          >
            {Icon ? (
              <Icon
                className={cn(iconSize, iconClass)}
                strokeWidth={1.5}
                aria-hidden="true"
              />
            ) : null}
          </div>
        )}

        <h1 className={cn(titleBase, titleClassName)}>{title}</h1>
        {subtitle ? (
          <p
            className={cn(
              "text-xs sm:text-sm text-muted-foreground",
              subtitleClassName
            )}
          >
            {subtitle}
          </p>
        ) : null}
      </div>
    </div>
  );
}
