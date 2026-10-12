import { InlineForm } from "@kit/components/board";
import { PersonAvatar } from "@kit/components/person-avatar";
import { Input } from "@kit/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@kit/ui/select";
import type { PipelineSnapshot, Stage } from "@shared/schema";
import { useState } from "react";
import type { NewDeal } from "./types";

/** Inline "New deal": a title, a value, and an owner when the board shows everyone's deals. */
export function NewDealForm({
  snapshot,
  stage,
  onCreate,
  onClose,
}: {
  snapshot: PipelineSnapshot;
  stage: Stage;
  onCreate: (deal: NewDeal) => Promise<string | null>;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [value, setValue] = useState("");
  const [ownerId, setOwnerId] = useState(snapshot.ownerId ?? snapshot.owners.find((o) => o.kind === "human")?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const amount = Number(value.replace(/\s/g, "").replace(",", "."));
  const valid = !!title.trim() && value.trim() !== "" && Number.isFinite(amount) && amount >= 0 && !!ownerId;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    const failure = await onCreate({ title: title.trim(), value: amount, stageId: stage.id, ownerId });
    setBusy(false);
    if (failure) setError(failure);
    else onClose();
  };

  return (
    <InlineForm
      busy={busy}
      error={error}
      canSubmit={valid}
      onSubmit={() => void submit()}
      onClose={onClose}
      extra={
        snapshot.ownerId === null && (
          <Select value={ownerId} onValueChange={setOwnerId} disabled={busy}>
            <SelectTrigger size="sm" className="h-7 max-w-[140px] px-2 text-xs" aria-label="Owner">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {snapshot.owners.map((o) => (
                <SelectItem key={o.id} value={o.id}>
                  <PersonAvatar person={o} className="size-4" />
                  {o.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )
      }
    >
      <Input
        autoFocus
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Company — what they buy"
        aria-label={`New deal in ${stage.name}`}
        aria-invalid={error ? true : undefined}
        disabled={busy}
      />
      <Input
        value={value}
        inputMode="decimal"
        onChange={(event) => setValue(event.target.value)}
        placeholder={`Value, ${snapshot.baseCurrency}`}
        aria-label="Deal value"
        className="tabular"
        disabled={busy}
      />
    </InlineForm>
  );
}
