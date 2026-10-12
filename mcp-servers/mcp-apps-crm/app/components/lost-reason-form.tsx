import { InlineForm } from "@kit/components/board";
import { Input } from "@kit/ui/input";
import { useState } from "react";

/** Asks why a deal was lost; the deal only moves once a reason is confirmed. */
export function LostReasonForm({
  title,
  reasons,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  title: string;
  reasons: string[];
  busy: boolean;
  error: string | null;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const trimmed = reason.trim();

  return (
    <InlineForm
      busy={busy}
      error={error}
      canSubmit={!!trimmed}
      submitLabel="Mark lost"
      onSubmit={() => trimmed && onConfirm(trimmed)}
      onClose={onCancel}
    >
      <p className="text-muted-foreground px-0.5 text-xs">
        Why was <span className="text-foreground font-medium">{title}</span> lost?
      </p>
      <div className="flex flex-wrap gap-1">
        {reasons.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setReason(option)}
            aria-pressed={trimmed === option}
            className="text-muted-foreground hover:bg-accent hover:text-foreground aria-pressed:border-input aria-pressed:bg-accent aria-pressed:text-foreground inline-flex h-5 cursor-pointer items-center rounded-full border px-1.5 text-[11px] leading-none"
          >
            {option}
          </button>
        ))}
      </div>
      <Input
        autoFocus
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Lost reason"
        aria-label="Lost reason"
        aria-invalid={error ? true : undefined}
        disabled={busy}
      />
    </InlineForm>
  );
}
