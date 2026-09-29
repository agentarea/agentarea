"use client";

import { useState, useTransition } from "react";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Plus } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { createProjectAction } from "@/lib/server-actions";

type CreateProjectDialogProps = {
  /** Controlled mode — lets the empty state open it without its own trigger. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  showTrigger?: boolean;
};

/**
 * A project is a name and two optional notes, which is a dialog's worth of
 * form. It used to be a route of its own, which meant a full navigation and a
 * back link to fill in one field.
 */
export function CreateProjectDialog({
  open: controlledOpen,
  onOpenChange,
  showTrigger = true,
}: CreateProjectDialogProps = {}) {
  const router = useWorkspaceRouter();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = onOpenChange ?? setUncontrolledOpen;
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const submit = () => {
    setError(null);
    startTransition(async () => {
      const { data, error: failure } = await createProjectAction({
        name: name.trim(),
        description: description.trim() || null,
        instructions: instructions.trim() || null,
      });

      if (failure) {
        setError(
          (failure as { detail?: string })?.detail ?? "Could not create project"
        );
        return;
      }

      setName("");
      setDescription("");
      setInstructions("");
      setOpen(false);

      const projectId = (data as { id?: string } | undefined)?.id;
      router.push(projectId ? `/projects/${projectId}` : "/projects");
      router.refresh();
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {showTrigger && (
        <DialogTrigger asChild>
          <Button className="shrink-0" size="xs">
            <Plus />
            New project
          </Button>
        </DialogTrigger>
      )}
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            A place to keep agents, skills and files that belong together.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="project-name">Name</Label>
            <Input
              id="project-name"
              placeholder="Inbound triage"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="project-description">Description</Label>
            <Input
              id="project-description"
              placeholder="What this project is for"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="project-instructions">Instructions</Label>
            <Textarea
              id="project-instructions"
              placeholder="Standing instructions for agents working in this project"
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              rows={4}
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}

          <DialogFooter>
            <Button type="submit" size="sm" disabled={pending || !name.trim()}>
              {pending ? "Creating…" : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
