"use client";

import * as React from "react";
import { ArrowRight } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/** AgentArea "Start agent" button — dark gradient pill, sliding arrow, grey when disabled. */
const startAgentVariants = cva(
  cn(
    "group relative flex w-full items-center justify-center overflow-hidden",
    "font-bold uppercase leading-none tracking-[0.04em] text-white",
    "bg-[linear-gradient(180deg,#262a33_0%,#15171c_58%,#0c0e12_100%)]",
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.09),inset_0_0_0_1px_rgba(255,255,255,0.04),0_1px_2px_rgba(8,10,15,0.45),0_10px_24px_-10px_rgba(8,10,15,0.62)]",
    "transition-[transform,box-shadow] duration-150 ease-out",
    "hover:-translate-y-[1.5px] hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.13),inset_0_0_0_1px_rgba(255,255,255,0.06),0_2px_5px_rgba(8,10,15,0.4),0_18px_34px_-10px_rgba(8,10,15,0.7)]",
    "active:translate-y-0 active:scale-[0.992]",
    "focus-visible:outline-none focus-visible:shadow-[inset_0_1px_0_rgba(255,255,255,0.1),0_0_0_3px_rgba(47,99,230,0.5),0_10px_24px_-10px_rgba(8,10,15,0.6)]",
    "disabled:cursor-not-allowed disabled:bg-none disabled:bg-[#eceef1] disabled:text-[#abaeb6] disabled:shadow-[inset_0_0_0_1px_#e2e4e8] disabled:hover:translate-y-0 disabled:hover:shadow-[inset_0_0_0_1px_#e2e4e8]"
  ),
  {
    variants: {
      size: {
        xs: "h-8 gap-3 rounded-[8px] text-[10.5px]",
        sm: "h-9 gap-3.5 rounded-[9px] text-[11.5px]",
        md: "h-11 gap-2 rounded-[11px] text-[13px]",
        lg: "h-[52px] gap-2.5 rounded-[13px] text-[14px]",
      },
    },
    defaultVariants: { size: "md" },
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
>(({ asChild = false, size = "md", className, children, disabled, isLoading = false, ...props }, ref) => {
  const icon = ICON[size ?? "md"];
  const childElement = asChild ? (React.Children.only(children) as React.ReactElement) : null;
  const label = childElement ? childElement.props.children : children;
  const content = (
    <>
      <img
        src="/simple-logo.svg"
        alt=""
        aria-hidden="true"
        width={icon}
        className="h-auto shrink-0 group-disabled:opacity-50"
      />
      <span>{label ?? "Start agent"}</span>
      <ArrowRight aria-hidden="true" size={icon} className="go-next shrink-0 group-disabled:!translate-x-0" />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 left-[-45%] w-[38%] -skew-x-[18deg] bg-[linear-gradient(100deg,transparent,rgba(255,255,255,0.22),transparent)] opacity-0 group-hover:animate-ba-shine group-disabled:hidden"
      />
    </>
  );

  if (asChild) {
    return React.cloneElement(childElement, {
      ...props,
      className: cn(startAgentVariants({ size }), className, childElement.props.className),
      children: content,
      "aria-disabled": disabled || isLoading || undefined,
    });
  }

  return (
    <button ref={ref} className={cn(startAgentVariants({ size }), className)} disabled={disabled || isLoading} {...props}>
      {content}
    </button>
  );
});

StartAgentButton.displayName = "StartAgentButton";
