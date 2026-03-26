"use client";

import { useState } from "react";
import { Plus, Trash2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";

interface AssociationItem {
  id: string;
  name: string;
}

interface AssociationSectionProps {
  title: string;
  items: AssociationItem[];
  allItems: AssociationItem[];
  onAdd: (id: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
  addLabel?: string;
  selectPlaceholder?: string;
}

export function AssociationSection({
  title,
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

  const available = allItems.filter((item) => !items.some((i) => i.id === item.id));

  const handleAdd = async () => {
    if (!selectedId) return;
    setIsAdding(true);
    try {
      await onAdd(selectedId);
      setShowAddDialog(false);
      setSelectedId("");
    } catch (err) {
      toast({ title: "Error", description: "Failed to add item", variant: "destructive" });
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemove = async (id: string) => {
    setRemovingId(id);
    try {
      await onRemove(id);
    } catch (err) {
      toast({ title: "Error", description: "Failed to remove item", variant: "destructive" });
    } finally {
      setRemovingId(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">
          {title} ({items.length})
        </h3>
        <Button size="xs" variant="outline" onClick={() => setShowAddDialog(true)}>
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          {addLabel}
        </Button>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No {title.toLowerCase()} yet.</p>
      ) : (
        <ul className="space-y-1">
          {items.map((item) => (
            <li
              key={item.id}
              className="flex items-center justify-between rounded border px-3 py-2 text-sm"
            >
              <span>{item.name}</span>
              <Button
                size="xs"
                variant="ghost"
                onClick={() => handleRemove(item.id)}
                disabled={removingId === item.id}
              >
                {removingId === item.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
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
              <p className="text-sm text-muted-foreground">No items available to add.</p>
            ) : (
              <select
                className="w-full rounded border bg-background px-3 py-2 text-sm"
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
            <Button onClick={handleAdd} disabled={!selectedId || isAdding || available.length === 0}>
              {isAdding ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
