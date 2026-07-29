"use client";

import { useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";

interface AssociationItem {
  id: string;
  name: string;
}

interface AssociationSectionProps {
  title: string;
  kind: Extract<EntityKind, "agent" | "skill" | "mcp">;
  description: string;
  items: AssociationItem[];
  allItems: AssociationItem[];
  onAdd: (id: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
  addLabel?: string;
  selectPlaceholder?: string;
}

export function AssociationSection({
  title,
  kind,
  description,
  items,
  allItems,
  onAdd,
  onRemove,
  addLabel = "Add",
  selectPlaceholder = "Select an item...",
}: AssociationSectionProps) {
  const { toast } = useToast();
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [isAdding, setIsAdding] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);

  const available = allItems.filter(
    (item) => !items.some((i) => i.id === item.id)
  );
  const tone = {
    agent:
      "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:ring-blue-800",
    skill:
      "bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-950 dark:text-violet-300 dark:ring-violet-800",
    mcp: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:ring-emerald-800",
  }[kind];

  const handleAdd = async () => {
    if (!selectedId) return;
    setIsAdding(true);
    try {
      await onAdd(selectedId);
      setShowAddDialog(false);
      setSelectedId("");
    } catch (_err) {
      toast({
        title: "Error",
        description: "Failed to add item",
        variant: "destructive",
      });
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemove = async (id: string) => {
    setRemovingId(id);
    try {
      await onRemove(id);
    } catch (_err) {
      toast({
        title: "Error",
        description: "Failed to remove item",
        variant: "destructive",
      });
    } finally {
      setRemovingId(null);
    }
  };

  return (
    <section className="relative z-10 flex min-h-[286px] flex-col rounded-xl border bg-card px-4 pb-4 pt-8 shadow-[0_14px_34px_-28px_rgba(15,23,42,0.65)] transition-[border-color,box-shadow,transform] duration-300 hover:-translate-y-0.5 hover:border-primary/20 hover:shadow-[0_18px_42px_-28px_rgba(15,23,42,0.7)] motion-reduce:transform-none">
      <span
        className={cn(
          "absolute -top-5 left-1/2 flex h-10 w-10 -translate-x-1/2 items-center justify-center rounded-xl bg-card ring-4 ring-background",
          tone
        )}
      >
        <EntityIcon kind={kind} className="h-[18px] w-[18px]" />
      </span>

      <div className="text-center">
        <div className="flex items-center justify-center gap-2">
          <h3 className="text-sm font-semibold">{title}</h3>
          <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-muted-foreground">
            {String(items.length).padStart(2, "0")}
          </span>
        </div>
        <p className="mx-auto mt-1.5 min-h-10 max-w-[260px] text-xs leading-5 text-muted-foreground">
          {description}
        </p>
      </div>

      <Button
        size="sm"
        variant="outline"
        className="mt-4 w-full border-dashed bg-muted/20 hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
        onClick={() => setShowAddDialog(true)}
      >
        <Plus className="mr-1.5 h-3.5 w-3.5" />
        {addLabel}
      </Button>

      {items.length === 0 ? (
        <div className="mt-3 flex flex-1 items-center justify-center rounded-lg border border-dashed bg-[radial-gradient(circle_at_1px_1px,hsl(var(--border))_1px,transparent_0)] p-4 [background-size:14px_14px]">
          <p className="rounded-md bg-card/90 px-3 py-1.5 text-center text-xs text-muted-foreground shadow-sm">
            No {title.toLowerCase()} connected yet
          </p>
        </div>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {items.map((item) => (
            <li
              key={item.id}
              className="group/item flex items-center justify-between rounded-lg border bg-background px-3 py-2 text-sm transition-colors hover:border-primary/20 hover:bg-muted/30"
            >
              <span className="min-w-0 truncate font-medium">{item.name}</span>
              <Button
                size="xs"
                variant="ghost"
                aria-label={`Remove ${item.name}`}
                className="ml-2 shrink-0 text-muted-foreground opacity-70 hover:text-destructive group-hover/item:opacity-100"
                onClick={() => handleRemove(item.id)}
                disabled={removingId === item.id}
              >
                {removingId === item.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
              </Button>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{addLabel}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {available.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No items available to add.
              </p>
            ) : (
              <select
                className="w-full rounded-md border bg-background px-3 py-2.5 text-sm outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
              >
                <option value="">{selectPlaceholder}</option>
                {available.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleAdd}
              disabled={!selectedId || isAdding || available.length === 0}
            >
              {isAdding ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
