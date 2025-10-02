import { cn } from "@/lib/utils";

interface TabProps {
    children: React.ReactNode;
    className?: string;
    isActive?: boolean;
    onClick?: () => void;
}

export default function Tab({ children, className, isActive = false, onClick }: TabProps) {
    return (
        <button       
            onClick={onClick}
            className={cn(
                "text-xs flex items-center gap-1 p-1",
                "transition-all duration-300",
                "cursor-pointer",
                className,
                isActive
                ? "bg-background text-primary bg-sidebar-accent rounded-sm"
                : "text-muted-foreground hover:text-foreground "
          )}>
            {children}
        </button>
    );
}