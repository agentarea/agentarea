import { cn } from "@/lib/utils";   

export default function Note({ children, className }: { children: React.ReactNode, className?: string }) {
  return (
    <div
      className={cn(
        "mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground/50 dark:bg-zinc-900",
        className
      )}
    >
      {children}
    </div>
  );
}