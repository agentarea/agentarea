import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "w-max inline-flex gap-1 items-center rounded-full border font-base transition-colors",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary/15 text-accent dark:bg-[#dce1ff]",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        disabled: "border-transparent bg-zinc-100 text-zinc-400",
        destructive:
          "border-transparent bg-destructive/15 text-destructive dark:bg-destructive/50 dark:text-white",
        outline: "text-foreground",
        light: "border-transparent bg-transparent text-muted-foreground/50",
        success: "border-transparent bg-green-100 text-green-500",
        blue: "border-transparent bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200",
        purple:
          "border-transparent bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-200",
        orange:
          "border-transparent bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-200",
        yellow:
          "border-transparent bg-yellow-100/70 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-200",
        gray: "border-transparent bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
        teal: "border-transparent bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-200",
        slate:
          "border-transparent bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
        indigo:
          "border-transparent bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-200",
        emerald:
          "border-transparent bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200",
        zinc: "border-transparent bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
        rose: "border-transparent bg-rose-100 text-rose-700 dark:bg-rose-900 dark:text-rose-200",
        neutral:
          "border-transparent bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
        amber:
          "border-transparent bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200",
        dark: "border-transparent bg-zinc-700 text-white dark:bg-zinc-100 dark:text-zinc-900",
      },
      size: {
        default: "text-xs px-2.5 py-0.5",
        sm: "text-[10px] px-1.5 py-0.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  size?: "default" | "sm";
}

function Badge({ className, variant, size = "default", ...props }: BadgeProps) {
  return (
    <div
      className={cn(badgeVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
