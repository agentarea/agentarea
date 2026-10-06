import * as React from "react";
import { cn } from "@/lib/utils";

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  variant?: "default" | "title";
  /** Short fixed text inside the field before the value, e.g. "@" or "$". */
  leading?: React.ReactNode;
  /** A control inside the field after the value, e.g. a reveal button. */
  trailing?: React.ReactNode;
};

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    { className, type, variant = "default", leading, trailing, ...props },
    ref
  ) => {
    const input = (
      <input
        type={type}
        className={cn(
          variant === "title"
            ? "h-12 w-full rounded-none border-0 border-b border-transparent bg-transparent px-0 py-1 text-xl font-bold text-foreground outline-none placeholder:text-muted-foreground focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-50 md:text-2xl"
            : "h-9 w-full rounded-md border border-input bg-white px-3 py-2 text-inputSize outline-none ring-0 transition-colors duration-300 file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-900 focus-visible:dark:border-accent-foreground",
          leading != null && "pl-7",
          trailing != null && "pr-9",
          className
        )}
        ref={ref}
        {...props}
      />
    );

    if (leading == null && trailing == null) return input;

    return (
      <div className="relative">
        {leading != null && (
          <span
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground"
          >
            {leading}
          </span>
        )}
        {input}
        {trailing != null && (
          <div className="absolute inset-y-0 right-0 flex items-center">
            {trailing}
          </div>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";

export { Input };
