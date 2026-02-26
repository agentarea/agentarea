import { Clock } from "lucide-react";
import Section from "./Section";

interface KeyMetricsProps {
  currentStatus: string;
  isActive: boolean;
  executionTime: string;
  formattedStart: string;
  formattedEnd: string;
}

export default function KeyMetrics({
  currentStatus,
  isActive,
  executionTime,
  formattedStart,
  formattedEnd,
}: KeyMetricsProps) {
  return (
    <Section title="Key metrics" contentClassName="text-xs grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Status
          </div>
          <div className="text-sm font-semibold text-foreground">
            {currentStatus}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {isActive ? "Task is currently active" : "Task is not running"}
          </div>
        </div>

        <div className="space-y-1">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Execution Time
          </div>
          <div className="text-sm font-semibold text-foreground">
            {executionTime || "N/A"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            Measured from start to completion
          </div>
        </div>

        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Clock className="h-3 w-3 text-primary" />
            Started
          </div>
          <div className="text-[13px] font-medium text-foreground">
            {formattedStart}
          </div>
        </div>

        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Clock className="h-3 w-3 text-muted-foreground" />
            Ended
          </div>
          <div className="text-[13px] font-medium text-foreground">
            {formattedEnd}
          </div>
        </div>
    </Section>
  );
}
