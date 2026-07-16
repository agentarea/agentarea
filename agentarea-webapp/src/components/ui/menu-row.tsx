import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Uppercase section label used to head a group of {@link MenuRow}s inside a
 * popover menu (e.g. the Skills "Display" menu and the Dashboard period picker).
 */
export function MenuSectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="px-2 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70">
      {children}
    </p>
  );
}

/** Thin divider between menu sections. */
export function MenuSeparator() {
  return <div className="my-1 h-px bg-border" />;
}

/**
 * A single selectable row in a popover menu: optional leading icon, a label,
 * and an optional trailing slot. The selected row is tinted with the primary
 * color. Shared by the Skills "Display" menu and the Dashboard period picker.
 */
export function MenuRow({
  icon,
  label,
  selected = false,
  onClick,
  trailing,
}: {
  icon?: ReactNode;
  label: ReactNode;
  selected?: boolean;
  onClick?: () => void;
  trailing?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-[12.5px]",
        selected ? "text-primary" : "text-foreground/80 hover:bg-muted"
      )}
    >
      {icon != null && (
        <span className={selected ? "text-primary" : "text-muted-foreground"}>
          {icon}
        </span>
      )}
      <span className="flex-1 text-left">{label}</span>
      {trailing}
    </button>
  );
}
