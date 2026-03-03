import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface HoverLinkProps {
  text?: string;
  className?: string;
}

export function HoverLink({ text, className }: HoverLinkProps) {
  return (
    <div className={cn("small-link text-muted-foreground/70 group-hover:text-primary gap-1 flex items-center text-[9px] opacity-70", className)}>
      <span className="opacity-0 group-hover:opacity-100 transition-opacity duration-500 uppercase">{text}</span>
      <ArrowUpRight className="h-[17px] w-[17px] group-hover:scale-110 transition-transform duration-500" strokeWidth={1.5} />
    </div>
  );
}

