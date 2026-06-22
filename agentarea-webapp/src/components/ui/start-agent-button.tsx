"use client";

import * as React from "react";
import { Slot, Slottable } from "@radix-ui/react-slot";
import { ArrowRight } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/** AgentArea "Start agent" button — dark gradient pill, sliding arrow, grey when disabled. */
const startAgentVariants = cva(
  "group relative flex w-full items-center justify-center overflow-hidden font-bold uppercase leading-none tracking-[0.04em] transition-[transform,box-shadow] duration-150 ease-out active:translate-y-0 active:scale-[0.992] focus-visible:outline-none disabled:cursor-not-allowed disabled:bg-none disabled:bg-[#eceef1] disabled:text-[#abaeb6] disabled:shadow-[inset_0_0_0_1px_#e2e4e8] disabled:hover:translate-y-0 disabled:hover:shadow-[inset_0_0_0_1px_#e2e4e8]",
  {
    variants: {
      light: {
        false:
          "text-white bg-[linear-gradient(180deg,#262a33_0%,#15171c_58%,#0c0e12_100%)] shadow-[inset_0_1px_0_rgba(255,255,255,0.09),inset_0_0_0_1px_rgba(255,255,255,0.04),0_1px_2px_rgba(8,10,15,0.45),0_10px_24px_-10px_rgba(8,10,15,0.62)] hover:-translate-y-[1.5px] hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.13),inset_0_0_0_1px_rgba(255,255,255,0.06),0_2px_5px_rgba(8,10,15,0.4),0_18px_34px_-10px_rgba(8,10,15,0.7)] focus-visible:shadow-[inset_0_1px_0_rgba(255,255,255,0.1),0_0_0_3px_rgba(47,99,230,0.5),0_10px_24px_-10px_rgba(8,10,15,0.6)]",
        true:
          "text-[#1b1f27] bg-[linear-gradient(180deg,#ffffff_0%,#f7f8fb_100%)] shadow-[inset_0_1px_0_rgba(255,255,255,0.96),inset_0_0_0_1px_rgba(205,213,225,0.9),0_1px_2px_rgba(15,23,42,0.08),0_10px_24px_-14px_rgba(15,23,42,0.18)] hover:-translate-y-[1.5px] hover:shadow-[inset_0_1px_0_rgba(255,255,255,1),inset_0_0_0_1px_rgba(191,200,214,0.95),0_3px_8px_rgba(15,23,42,0.08),0_16px_24px_-16px_rgba(15,23,42,0.18)] focus-visible:shadow-[inset_0_1px_0_rgba(255,255,255,1),0_0_0_3px_rgba(47,99,230,0.18),0_10px_24px_-12px_rgba(15,23,42,0.18)]",
      },
      size: {
        xs: "h-8 gap-3 rounded-[8px] text-[10.5px]",
        sm: "h-9 gap-3.5 rounded-[9px] text-[11.5px]",
        md: "h-11 gap-2 rounded-[11px] text-[13px]",
        lg: "h-[52px] gap-2.5 rounded-[13px] text-[14px]",
      },
    },
    defaultVariants: { size: "md", light: false },
  }
);

const ICON: Record<
  NonNullable<VariantProps<typeof startAgentVariants>["size"]>,
  number
> = {
  xs: 13,
  sm: 14,
  md: 16,
  lg: 18,
};

export interface StartAgentButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof startAgentVariants> {
  asChild?: boolean;
  isLoading?: boolean;
}

export const StartAgentButton = React.forwardRef<
  HTMLButtonElement,
  StartAgentButtonProps
>(({ asChild = false, size = "md", light = false, className, children, disabled, isLoading = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  const isDisabled = disabled || isLoading;
  const icon = ICON[size ?? "md"];

  return (
    <Comp
      ref={ref}
      className={cn(startAgentVariants({ size, light }), className)}
      disabled={asChild ? undefined : isDisabled}
      aria-disabled={asChild && isDisabled ? true : undefined}
      tabIndex={asChild && isDisabled ? -1 : undefined}
      {...props}
    >
      <img
        src="/simple-logo.svg"
        alt=""
        aria-hidden="true"
        width={icon}
        className={cn(
          "h-auto shrink-0 group-disabled:opacity-50",
          light ? "invert" : null
        )}
      />
      <Slottable>
        <span>{children ?? "Start agent"}</span>
      </Slottable>
      <ArrowRight
        aria-hidden="true"
        size={icon}
        className="go-next shrink-0 group-disabled:!translate-x-0"
      />
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute inset-y-0 left-[-45%] w-[38%] -skew-x-[18deg] opacity-0 group-hover:animate-ba-shine group-disabled:hidden",
          light
            ? "bg-[linear-gradient(100deg,transparent,rgba(15,23,42,0.08),transparent)]"
            : "bg-[linear-gradient(100deg,transparent,rgba(255,255,255,0.22),transparent)]"
        )}
      />
    </Comp>
  );
});

StartAgentButton.displayName = "StartAgentButton";
