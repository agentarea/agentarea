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
  invertIconInDark?: boolean;
  children?: ReactNode;
  subtitle?: ReactNode;
  topRight?: ReactNode;
  type?: "view" | "config" | "edit";
  className?: string;
}

export default function LinkedCard({
  href,
  onClick,
  title,
  icon,
  invertIconInDark = false,
  children,
  subtitle,
  topRight,
  type = "view",
  className,
}: LinkedCardProps) {
  const hasIcon = icon !== undefined && icon !== null;
  const isStringIcon = typeof icon === "string";
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
        "group h-full flex flex-col justify-between px-4 py-4 cursor-pointer transition-all duration-300",
        "border border-zinc-200 dark:border-zinc-800",
        "bg-white dark:bg-zinc-900",
        "hover:shadow-lg hover:shadow-zinc-200/50 dark:hover:shadow-zinc-950/50",
        "hover:border-primary/20 dark:hover:border-primary/40",
        "hover:bg-white dark:hover:bg-zinc-800",
        "hover:-translate-y-0.5 relative",
        "active:scale-[0.99]",
        className
      )}
      onClick={onClick}
    >
        <div className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03] pointer-events-none" 
           style={{
             backgroundImage: `repeating-linear-gradient(
               -45deg,
               currentColor,
               currentColor 1px,
               transparent 1px,
               transparent 10px
             )`
           }} 
        />

      <div className="flex flex-col h-full z-10">
        <div className={cn("flex gap-3 mb-2", subtitle ? "items-start" : "items-center")}>
          {hasIcon ? (
            <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-primary/5 text-primary dark:bg-zinc-800 dark:text-zinc-200 group-hover:bg-primary/10 dark:group-hover:bg-zinc-700/80 dark:group-hover:text-zinc-50 transition-colors duration-300 border border-transparent dark:border-zinc-700/50 dark:group-hover:border-zinc-600">
              {isStringIcon ? (
                <img
                  src={icon as string}
                  alt={title}
                  className={cn(
                    "h-6 w-6 rounded object-contain transition-transform group-hover:scale-110 duration-300",
                    invertIconInDark && "dark:invert"
                  )}
                />
              ) : IconComponent ? (
                <IconComponent className="h-5 w-5 transition-colors duration-300" />
              ) : isValidElement(icon) ? (
                icon
              ) : (
                <Sparkles className="h-5 w-5 transition-colors duration-300" />
              )}
            </div>
          ) : null}

          <div className="min-w-0 flex-1">
            <div className={cn("flex justify-between gap-3", subtitle ? "items-start" : "items-center")}>
              <div className={cn("min-w-0 flex-1", subtitle ? "pt-0.5" : null)}>
                <h4
                  className={cn(
                    "block truncate font-medium text-[15px] text-zinc-900 dark:text-zinc-100 leading-tight tracking-tight group-hover:text-primary dark:group-hover:text-zinc-50 transition-colors duration-300",
                    subtitle ? "mb-1" : null
                  )}
                >
                  {title}
                </h4>
                {subtitle ? (
                  <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                    {subtitle}
                  </div>
                ) : null}
              </div>
              {topRight ? <div className="flex-shrink-0">{topRight}</div> : null}
            </div>
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
