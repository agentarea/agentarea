import * as React from "react";
import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<"textarea"> & { variant?: "default" | "document" }
>(({ className, variant = "default", ...props }, ref) => {
  return (
    <textarea
      className={cn(
        variant === "document"
          ? "flex min-h-40 w-full resize-y rounded-sm border-0 bg-transparent px-0 py-2 text-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-border focus-visible:ring-offset-4 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
          : "flex min-h-[60px] w-full rounded-md border border-input bg-white px-3 py-2 text-base text-inputSize outline-none ring-0 transition-all duration-300 placeholder:text-muted-foreground focus:ring-0 focus-visible:border-primary focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-900 focus-visible:dark:border-accent-foreground",
        className
      )}
      ref={ref}
      {...props}
    />
  );
});
Textarea.displayName = "Textarea";

export { Textarea };
