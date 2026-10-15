import { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import Link from "@/components/WorkspaceLink";
import { cn } from "@/lib/utils";

interface ActionLinkProps {
  href?: string;
  onClick?: () => void;
  children: ReactNode;
  className?: string;
  icon?: ReactNode;
  /** Open `href` in a new browser tab, leaving the page where it is. */
  newTab?: boolean;
}

export default function ActionLink({
  href,
  onClick,
  children,
  className,
  icon = <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />,
  newTab = false,
}: ActionLinkProps) {
  const baseClassName = cn(
    "inline-flex w-full items-center justify-between rounded-md border border-border/70 bg-background px-3 py-1.5 text-[13px] text-foreground hover:bg-muted/70 transition-colors",
    className
  );

  if (href) {
    return (
      <Link
        href={href}
        className={baseClassName}
        {...(newTab ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      >
        <span>{children}</span>
        {icon}
      </Link>
    );
  }

  return (
    <button type="button" onClick={onClick} className={baseClassName}>
      <span>{children}</span>
      {icon}
    </button>
  );
}
