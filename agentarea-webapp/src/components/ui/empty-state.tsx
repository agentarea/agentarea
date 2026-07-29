import * as React from "react";
import { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title: string;
  description: string;
  icons?: LucideIcon[];
  action?: {
    label: string;
    onClick: () => void;
  };
  additionAction?: {
    label: string;
    onClick: () => void;
  };
  /** Tint applied to the emphasized (center / single) icon. */
  accentClassName?: string;
  className?: string;
}

function IconTile({
  icon: Icon,
  className,
  iconClassName,
}: {
  icon: LucideIcon;
  className?: string;
  iconClassName?: string;
}) {
  return (
    <div
      className={cn(
        "grid size-11 place-items-center rounded-xl bg-background shadow-md ring-1 ring-border transition duration-500 group-hover:duration-200",
        className
      )}
    >
      <Icon className={cn("h-5 w-5 text-muted-foreground", iconClassName)} />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icons = [],
  action,
  className,
  additionAction,
  accentClassName,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "border-border bg-background text-center hover:border-border/80",
        "w-full max-w-[620px] rounded-xl border-2 border-dashed p-14",
        "group transition duration-500 hover:bg-muted/50 hover:duration-200",
        className
      )}
    >
      <div className="isolate flex justify-center">
        {icons.length === 3 ? (
          <>
            <IconTile
              icon={icons[0]}
              className="relative left-2 top-1 -rotate-6 group-hover:-translate-x-4 group-hover:-translate-y-0.5 group-hover:-rotate-12"
            />
            <IconTile
              icon={icons[1]}
              iconClassName={accentClassName}
              className="relative z-10 group-hover:-translate-y-0.5"
            />
            <IconTile
              icon={icons[2]}
              className="relative right-2 top-1 rotate-6 group-hover:translate-x-4 group-hover:-translate-y-0.5 group-hover:rotate-12"
            />
          </>
        ) : (
          icons[0] && (
            <IconTile
              icon={icons[0]}
              iconClassName={accentClassName}
              className="group-hover:-translate-y-0.5"
            />
          )
        )}
      </div>
      <h3 className="mt-5 text-[13.5px] font-semibold text-foreground">
        {title}
      </h3>
      <p className="mx-auto mt-1 max-w-[320px] whitespace-pre-line text-[12px] leading-relaxed text-muted-foreground">
        {description}
      </p>
      <div className="mt-5 flex flex-col justify-center gap-2 sm:flex-row">
        {action && (
          <Button
            size="sm"
            onClick={action.onClick}
            className={cn("shadow-sm active:shadow-none")}
          >
            {action.label}
          </Button>
        )}

        {additionAction && (
          <Button
            size="sm"
            onClick={additionAction.onClick}
            variant="outline"
            className={cn("shadow-sm active:shadow-none")}
          >
            {additionAction.label}
          </Button>
        )}
      </div>
    </div>
  );
}
