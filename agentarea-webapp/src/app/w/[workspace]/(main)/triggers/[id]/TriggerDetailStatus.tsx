"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  getTriggerStatusPresentation,
  type StatusPresentation,
} from "@/lib/status";

type TriggerDetailStatusValue = {
  active: boolean;
  setActive: (active: boolean) => void;
};

const TriggerDetailStatusContext =
  createContext<TriggerDetailStatusValue | null>(null);

export function TriggerDetailStatusProvider({
  initialActive,
  children,
}: {
  initialActive: boolean;
  children: ReactNode;
}) {
  const [active, setActive] = useState(initialActive);
  return (
    <TriggerDetailStatusContext.Provider value={{ active, setActive }}>
      {children}
    </TriggerDetailStatusContext.Provider>
  );
}

export function useTriggerDetailStatus() {
  const status = useContext(TriggerDetailStatusContext);
  if (!status) {
    throw new Error("Trigger detail status requires its provider");
  }
  return status;
}

export function TriggerStatusBadge({
  status,
  className,
}: {
  status: StatusPresentation;
  className?: string;
}) {
  const t = useTranslations("TriggersPage.status");
  const { active } = useTriggerDetailStatus();
  const presentation =
    status.kind === "failed" || status.kind === "attention"
      ? status
      : getTriggerStatusPresentation(active ? "active" : "paused");

  return (
    <StatusIndicator kind={presentation.kind} className={className}>
      {presentation.labelKey ? t(presentation.labelKey) : presentation.label}
    </StatusIndicator>
  );
}
