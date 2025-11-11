import { cn } from "@/lib/utils";

interface LoadingSpinnerProps {
  size?: "sm" | "md" | "lg";
  text?: string;
  fullScreen?: boolean;
  className?: string;
  variant?: "light" | "primary";
}

export function LoadingSpinner({
  size = "md",
  variant = "primary",
  text,
  fullScreen = false,
  className = "",
}: LoadingSpinnerProps) {
  const sizeClasses = {
    sm: "h-4 w-4 loader-small",
    md: "h-8 w-8 loader-medium",
    lg: "h-10 w-10 loader-large",
  };

  const variantClasses = {
    light: "loader-light",
    primary: "loader-primary",
  };

  const spinner = (
    <div className="text-center">
      <div
        className={cn(
          "loader",
          sizeClasses[size],
          variantClasses[variant],
        )}
      ></div>
      {text && (
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">{text}</p>
      )}
    </div>
  );

  if (fullScreen) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
        <div className="mx-auto max-w-6xl px-4 py-4">
          <div className="flex items-center justify-center py-8">{spinner}</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex items-center justify-center ${className}`}>
      {spinner}
    </div>
  );
}
