import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** How the control column sizes itself next to the title. */
const CONTROL_CLASS = {
  /** A button or a toggle: as wide as it is. */
  fit: "shrink-0 items-center gap-2",
  /** A text field and its errors: fixed width, full width on a phone. */
  field: "w-full flex-col items-stretch gap-1 sm:w-72",
  /** A wide control, e.g. a drop zone: shares the row with the title. */
  fill: "min-w-0 flex-1 basis-72 items-stretch gap-4",
};

/**
 * One setting inside a {@link SettingsSection} panel: title and description on
 * the left, the control on the right. On a phone the control drops below.
 */
export default function SettingsRow({
  tile,
  title,
  description,
  htmlFor,
  control = "fit",
  below,
  children,
}: {
  /** Optional leading mark, e.g. a provider logo. */
  tile?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  /** Id of the control, so the title labels it. */
  htmlFor?: string;
  control?: keyof typeof CONTROL_CLASS;
  /** Full-width content under title and control, still inside the row, e.g. an editor it opened. */
  below?: ReactNode;
  children?: ReactNode;
}) {
  const Title = htmlFor ? "label" : "div";

  return (
    <div className="flex min-h-[58px] flex-wrap items-center gap-x-4 gap-y-2 border-b border-border/60 px-4 py-3 last:border-b-0">
      {tile}
      <div className="min-w-0 flex-1 basis-48">
        <Title htmlFor={htmlFor} className="block text-sm font-medium">
          {title}
        </Title>
        {description != null && (
          <div className="mt-0.5 text-xs text-muted-foreground">
            {description}
          </div>
        )}
      </div>
      {children != null && (
        <div className={cn("flex", CONTROL_CLASS[control])}>{children}</div>
      )}
      {below != null && below !== false && (
        <div className="basis-full">{below}</div>
      )}
    </div>
  );
}
