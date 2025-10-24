import { cn } from "@/lib/utils";

interface TabProps {
  children: React.ReactNode;
  className?: string;
  isActive?: boolean;
  onClick?: () => void;
}

export default function Tab({
  children,
  className,
  isActive = false,
  onClick,
}: TabProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 p-1 text-xs",
        "transition-all duration-300",
        "cursor-pointer",
        className,
        isActive
          ? "rounded-sm bg-background bg-sidebar-accent text-primary"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}
