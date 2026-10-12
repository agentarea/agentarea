import { InlineForm } from "@kit/components/board";
import { Input } from "@kit/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@kit/ui/select";
import type { BoardSnapshot } from "@shared/schema";
import type { Status } from "@shared/tasks";
import { useState } from "react";
import { STATUS_META } from "@/lib/meta";

/** Inline "New issue": a title, and a project when the board spans several. */
export function NewIssueForm({
  snapshot,
  status,
  onCreate,
  onClose,
}: {
  snapshot: BoardSnapshot;
  status: Status;
  onCreate: (input: { title: string; project: string; status: Status }) => Promise<string | null>;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [project, setProject] = useState(snapshot.project ?? snapshot.projects[0]?.key ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    const failure = await onCreate({ title: title.trim(), project, status });
    setBusy(false);
    if (failure) setError(failure);
    else onClose();
  };

  return (
    <InlineForm
      busy={busy}
      error={error}
      canSubmit={!!title.trim()}
      onSubmit={() => void submit()}
      onClose={onClose}
      extra={
        snapshot.project === null && (
          <Select value={project} onValueChange={setProject} disabled={busy}>
            <SelectTrigger size="sm" className="h-7 px-2 text-xs" aria-label="Project">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {snapshot.projects.map((p) => (
                <SelectItem key={p.key} value={p.key}>
                  {p.key} · {p.name}
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
        placeholder="Issue title"
        aria-label={`New issue in ${STATUS_META[status].label}`}
        aria-invalid={error ? true : undefined}
        disabled={busy}
      />
    </InlineForm>
  );
}
