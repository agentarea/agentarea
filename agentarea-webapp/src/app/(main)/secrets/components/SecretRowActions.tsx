"use client";

import { MoreHorizontal } from "lucide-react";
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
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { deleteSecretAction, rotateSecretAction } from "../actions";
import type { Secret } from "./SecretsTable";

export function SecretRowActions({ secret }: { secret: Secret }) {
  const router = useRouter();
  const [mode, setMode] = useState<"rotate" | "delete" | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const close = () => {
    setMode(null);
    setValue("");
    setError(null);
  };

  const run = (action: () => Promise<{ error: string | null }>) => {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (result.error) {
        setError(result.error);
        return;
      }
      close();
      router.refresh();
    });
  };

  const usageCount = secret.used_by?.length ?? 0;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={`Actions for ${secret.name}`}>
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {/* preventDefault keeps the menu from taking focus back as it closes,
              which otherwise dismisses the dialog in the same tick it opens. */}
          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault();
              setMode("rotate");
            }}
          >
            Replace value
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault();
              setMode("delete");
            }}
            className="text-destructive"
          >
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={mode === "rotate"} onOpenChange={(o) => !o && close()}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Replace value</DialogTitle>
            <DialogDescription>
              {usageCount > 0
                ? `${secret.name} is used in ${usageCount} place${usageCount === 1 ? "" : "s"}. All of them start using the new value immediately.`
                : `Sets a new value for ${secret.name}.`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="rotate-value">New value</Label>
            <Input
              id="rotate-value"
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
            />
          </div>
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button variant="ghost" onClick={close} disabled={pending}>
              Cancel
            </Button>
            <Button
              onClick={() => run(() => rotateSecretAction(secret.id, value))}
              disabled={pending || !value}
            >
              {pending ? "Saving…" : "Replace"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={mode === "delete"} onOpenChange={(o) => !o && close()}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {secret.name}?</DialogTitle>
            <DialogDescription>
              {usageCount > 0
                ? "Something still uses this secret. Detach it there first — deleting is refused while anything points at it."
                : "This cannot be undone."}
            </DialogDescription>
          </DialogHeader>
          {usageCount > 0 ? (
            <ul className="space-y-1 text-sm text-muted-foreground">
              {secret.used_by?.map((c) => (
                <li key={`${c.consumer_type}-${c.consumer_id}-${c.field}`}>
                  {c.consumer_type} · {c.field}
                </li>
              ))}
            </ul>
          ) : null}
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button variant="ghost" onClick={close} disabled={pending}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => run(() => deleteSecretAction(secret.id))}
              disabled={pending}
            >
              {pending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
