import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface HoverLinkProps {
  text: string;
  className?: string;
  leadingIcon?: ReactNode;
}

export function HoverLink({ text, className, leadingIcon }: HoverLinkProps) {
  return (
    <span
      className={cn(
        "small-link flex items-center gap-1 text-[9px] text-muted-foreground/70 opacity-70 group-hover:text-primary group-focus-visible:text-primary",
        className
      )}
    >
      {leadingIcon}
      <span className="uppercase opacity-0 transition-opacity duration-500 motion-reduce:transition-none group-hover:opacity-100 group-focus-visible:opacity-100">
        {text}
      </span>
      {!leadingIcon && (
        <ArrowUpRight
          className="h-[17px] w-[17px] transition-transform duration-500 motion-reduce:transition-none group-hover:scale-110 group-focus-visible:scale-110"
          strokeWidth={1.5}
        />
      )}
    </span>
  );
}
