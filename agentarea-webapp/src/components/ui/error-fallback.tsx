"use client";

import { AlertTriangle, RefreshCw, Home } from "lucide-react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ErrorFallbackProps {
  error?: Error | null;
  reset?: () => void;
  title?: string;
  description?: string;
  showHomeButton?: boolean;
  onHomeClick?: () => void;
  className?: string;
  variant?: "default" | "compact" | "full";
}

export function ErrorFallback({
  error,
  reset,
  title = "Something went wrong",
  description = "An unexpected error occurred. Please try again.",
  showHomeButton = false,
  onHomeClick,
  className,
  variant = "default",
}: ErrorFallbackProps) {
  const handleGoHome = () => {
    if (onHomeClick) {
      onHomeClick();
    } else {
      window.location.href = "/workplace";
    }
  };

  const isCompact = variant === "compact";
  const isFull = variant === "full";

  return (
    <motion.div
      className={cn(
        "flex flex-col items-center justify-center p-8",
        isFull && "min-h-screen w-full",
        isCompact && "p-4",
        className
      )}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div
        className={cn(
          "flex flex-col items-center rounded-lg border border-destructive/20 bg-background p-8 text-center",
          isFull && "max-w-lg",
          isCompact && "p-4"
        )}
      >
        <div
          className={cn(
            "mb-4 rounded-full bg-destructive/10 p-4",
            isCompact && "mb-2 p-2"
          )}
        >
          <AlertTriangle
            className={cn(
              "text-destructive",
              isCompact ? "h-6 w-6" : "h-10 w-10"
            )}
          />
        </div>

        <h2
          className={cn(
            "font-semibold text-foreground",
            isCompact ? "text-base" : "mb-2 text-xl"
          )}
        >
          {title}
        </h2>

        {!isCompact && (
          <p className="mb-6 max-w-md text-sm text-muted-foreground">
            {description}
          </p>
        )}

        {process.env.NODE_ENV === "development" && error?.message && (
          <div className="mb-4 max-w-md overflow-auto rounded-md bg-muted p-3 text-left">
            <p className="font-mono text-xs text-destructive">
              {error.message}
            </p>
          </div>
        )}

        <div className="flex gap-3">
          {reset && (
            <Button
              variant="default"
              size={isCompact ? "sm" : "default"}
              onClick={reset}
              className="gap-2"
            >
              <RefreshCw className="h-4 w-4" />
              Try again
            </Button>
          )}

          {showHomeButton && (
            <Button
              variant="outline"
              size={isCompact ? "sm" : "default"}
              onClick={handleGoHome}
              className="gap-2"
            >
              <Home className="h-4 w-4" />
              Go home
            </Button>
          )}
        </div>
      </div>
    </motion.div>
  );
}

export default ErrorFallback;
