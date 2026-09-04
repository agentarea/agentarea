import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { LoadingSpinner } from "@/components/LoadingSpinner";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/70",
        destructiveOutline:
          "border border-destructive/20 text-destructive bg-background shadow-sm hover:bg-destructive/30 dark:border-destructive dark:text-zinc-400 dark:bg-destructive/20 dark:hover:bg-destructive/40 dark:hover:text-white",
        outline:
          "border border-input bg-transparent shadow-sm hover:bg-accent/20 dark:hover:bg-accent/10 hover:border-accent/20 dark:hover:border-accent/70 hover:text-accent dark:border-zinc-500",
        secondary:
          "bg-secondary text-secondary-foreground shadow-sm hover:text-accent ",
        ghost:
          "hover:bg-primary/10 hover:text-accent/80 dark:hover:text-accent-foreground dark:hover:bg-primary/30",
        link: "text-primary underline-offset-4 hover:underline",
      },
      // `[&_svg]:size-*` outranks any `h-4 w-4` a call site puts on the glyph,
      // so icon size can only be set here. `xs` gets 14px to keep the glyph
      // within the cap height of its 12px label.
      size: {
        default: "h-9 px-4 py-2 [&_svg]:size-4",
        sm: "h-8 rounded-md px-3 text-xs [&_svg]:size-4",
        xs: "h-6 rounded-sm px-1 text-xs font-normal gap-1 [&_svg]:size-3.5",
        lg: "h-10 rounded-md px-8 [&_svg]:size-4",
        icon: "h-9 w-9 [&_svg]:size-4",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  isLoading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, isLoading = false, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    const isDisabled = disabled || isLoading;
    
    if (asChild) {
      return (
        <Comp
          className={cn(buttonVariants({ variant, size, className }))}
          ref={ref}
          disabled={isDisabled}
          {...props}
        >
          {children}
        </Comp>
      );
    }

    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={isDisabled}
        {...props}
      >
        {isLoading && <LoadingSpinner variant="light" size="sm" />}
        {children}
      </Comp>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
