export type StatusTone =
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "neutral";

export type StatusIndicatorSize = "default" | "sm";

export type StatusPresentation = {
  label: string;
  tone: StatusTone;
  pulse?: boolean;
};

export type StatusResolver = (status: string) => StatusPresentation;
