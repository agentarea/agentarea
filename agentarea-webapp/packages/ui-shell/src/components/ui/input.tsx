import * as React from "react";
import { cn } from "../../lib/utils";

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  variant?: "default" | "title";
};

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, variant = "default", ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          variant === "title"
            ? "h-12 w-full rounded-none border-0 border-b border-transparent bg-transparent px-0 py-1 text-xl font-bold text-foreground outline-none placeholder:text-muted-foreground/60 focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-50 md:text-2xl"
            : "h-9 w-full rounded-md border border-input bg-white px-3 py-2 text-inputSize outline-none ring-0 transition-all duration-300 file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-900 focus-visible:dark:border-accent-foreground",
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
