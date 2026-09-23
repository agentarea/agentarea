"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import type { SecretResponse } from "@/api/client/types.gen";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createSecretAction } from "../actions";

type CreateSecretDialogProps = {
  /** Controlled mode — lets an empty state open the dialog without a trigger. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  showTrigger?: boolean;
  /** Set by a picker that wants the new secret rather than a page reload. */
  onCreated?: (secret: SecretResponse) => void;
};

export function CreateSecretDialog({
  open: controlledOpen,
  onOpenChange,
  showTrigger = true,
  onCreated,
}: CreateSecretDialogProps = {}) {
  const router = useRouter();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = onOpenChange ?? setUncontrolledOpen;
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const submit = () => {
    setError(null);
    startTransition(async () => {
      // Name rules and reserved prefixes are the server's to enforce — it owns
      // the list of names the platform already uses — so its message is shown
      // rather than a guess made here.
      const result = await createSecretAction({ name, value, description });
      if (result.error !== null) {
        setError(result.error);
        return;
      }
      setName("");
      setValue("");
      setDescription("");
      setOpen(false);
      if (onCreated) {
        onCreated(result.secret);
        return;
      }
      router.refresh();
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {showTrigger && (
        <DialogTrigger asChild>
          <Button className="shrink-0" size="xs">
            <Plus />
            New secret
          </Button>
        </DialogTrigger>
      )}
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New secret</DialogTitle>
          <DialogDescription>
            Stored encrypted. You won&apos;t be able to read it back — only
            replace it.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="secret-name">Name</Label>
            <Input
              id="secret-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="openai-key"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              Lowercase letters, digits, <code>-</code> and <code>_</code>.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="secret-value">Value</Label>
            <Input
              id="secret-value"
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="secret-description">Description (optional)</Label>
            <Input
              id="secret-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Which account this key belongs to"
            />
          </div>

          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setOpen(false)}
            disabled={pending}
          >
            Cancel
          </Button>
          <Button onClick={submit} disabled={pending || !name || !value}>
            {pending ? "Saving…" : "Create secret"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
