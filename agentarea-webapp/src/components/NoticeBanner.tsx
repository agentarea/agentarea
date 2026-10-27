import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

/** The one in-page banner (Design.md, "Status / banners"); at most one per page. */
export default function NoticeBanner({
  title,
  children,
  action,
  className,
}: {
  title: React.ReactNode;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-200",
        className
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">{title}</div>
        {children && <div className="text-xs">{children}</div>}
      </div>
      {action}
    </div>
  );
}
