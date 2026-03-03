import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Sparkles } from "lucide-react";
import { HoverLink } from "@/components/ui/hover-link";
import { ReactNode, ComponentType, isValidElement } from "react";
import { cn } from "@/lib/utils";

interface LinkedCardProps {
  href?: string;
  onClick?: () => void;
  title: string;
  icon?: string | ComponentType<{ className?: string }> | ReactNode;
  children?: ReactNode;
  subtitle?: ReactNode;
  type?: "view" | "config" | "edit";
  className?: string;
}

export default function LinkedCard({
  href,
  onClick,
  title,
  icon,
  children,
  subtitle,
  type = "view",
  className,
}: LinkedCardProps) {
  const isStringIcon = typeof icon === "string";
  const isComponentIcon = typeof icon === "function";
  // Check if icon is a Lucide component (function) or React Element
  const isLucideIcon = typeof icon === 'object' && icon !== null && 'render' in icon; // Lucide icons are exotic objects
  const isFunctionComponent = typeof icon === 'function';
  
  const IconComponent = (isLucideIcon || isFunctionComponent ? icon : null) as
    | ComponentType<{ className?: string }>
    | null;

  // Debug icon types
  // console.log(`LinkedCard icon type: ${typeof icon}, isComponent: ${isComponentIcon}, isElement: ${isValidElement(icon)}`);

  const CardContent = (
    <Card
      className={cn(
        "group h-full flex flex-col justify-between px-4 py-4 cursor-pointer transition-all hover:shadow-md hover:border-primary/20",
        className
      )}
      onClick={onClick}
    >
      <div className="flex flex-col h-full">
        <div className="flex gap-3 mb-2">
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-700/50">
            {isStringIcon ? (
              <img
                src={icon as string}
                alt={title}
                className="h-5 w-5 rounded object-contain"
              />
            ) : IconComponent ? (
              <IconComponent className="h-4 w-4 text-zinc-500 dark:text-zinc-400" />
            ) : isValidElement(icon) ? (
              icon
            ) : (
              <Sparkles className="h-4 w-4 text-zinc-500 dark:text-zinc-400" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h4
              className={cn(
                "truncate font-medium text-sm text-zinc-900 dark:text-zinc-100 leading-tight",
                subtitle ? "mb-1.5" : "h-full flex items-center"
              )}
            >
              {title}
            </h4>
            {subtitle ? (
              <div className="flex flex-wrap items-center gap-2">{subtitle}</div>
            ) : null}
          </div>
        </div>
        
        {children && (
          <div className="mt-auto py-2">
            {children}
          </div>
        )}
      </div>

      <div className="flex justify-end -mb-2 -mt-4 -mr-2">
        <HoverLink
          text={type === "config" ? "Configure" : type === "edit" ? "Edit" : "View"}
        />
      </div>
    </Card>
  );

  if (href) {
    return (
      <Link href={href} className="block h-full">
        {CardContent}
      </Link>
    );
  }

  return (
    <div
      className="block h-full"
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (!onClick) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {CardContent}
    </div>
  );
}
