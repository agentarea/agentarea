import { useTranslations } from "next-intl";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  getTaskStatusPresentation,
  type StatusIndicatorSize,
} from "@/lib/status";

/**
 * How a task's status reads on screen — tone, marker, translated caption — in
 * one place. Every surface that shows a task status goes through this, so a
 * change to the visual language lands everywhere at once instead of in
 * whichever call sites happened to be updated.
 */
interface TaskStatusProps {
  status: string;
  size?: StatusIndicatorSize;
  /**
   * `always` — caption is always rendered.
   * `auto` — caption is dropped for the check, which needs no words; the dot
   * statuses keep theirs, since several of them share a tone and would be
   * indistinguishable as bare markers.
   * `never` — caption is never rendered; for dense rows that name the task
   * themselves.
   */
  caption?: "always" | "auto" | "never";
  className?: string;
}

/** The translated status name on its own, for prose that can't take a marker. */
export function useTaskStatusLabel(status: string): string {
  const tStatus = useTranslations("TasksPage.status");
  const presentation = getTaskStatusPresentation(status);
  return presentation.labelKey
    ? tStatus(presentation.labelKey)
    : presentation.label;
}

export function TaskStatus({
  status,
  size = "sm",
  caption = "always",
  className,
}: TaskStatusProps) {
  const presentation = getTaskStatusPresentation(status);
  const label = useTaskStatusLabel(status);
  const showCaption =
    caption === "always" ||
    (caption === "auto" && presentation.icon !== "check");

  return (
    <StatusIndicator
      size={size}
      tone={presentation.tone}
      pulse={presentation.pulse}
      icon={presentation.icon}
      className={className}
      // The marker itself is aria-hidden, so a captionless indicator has to
      // carry the name on the root; the tooltip comes along for free.
      {...(showCaption ? {} : { role: "img", "aria-label": label, title: label })}
    >
      {showCaption ? label : null}
    </StatusIndicator>
  );
}
