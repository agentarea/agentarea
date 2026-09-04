"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
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

export function CreateSecretDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
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
      if (result.error) {
        setError(result.error);
        return;
      }
      setName("");
      setValue("");
      setDescription("");
      setOpen(false);
      router.refresh();
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="mr-1 h-4 w-4" />
          New secret
        </Button>
      </DialogTrigger>
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
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
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
