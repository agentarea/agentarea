"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { Check, ChevronsUpDown, Plus } from "lucide-react";
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
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import { createWorkspaceAction } from "@/lib/workspace-actions";
import {
  WORKSPACE_HOME,
  workspacePath,
  workspaceSection,
} from "@/lib/workspace-routes";
import type { Workspace } from "@/lib/workspaces";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";

function WorkspaceIcon({
  workspace,
  size,
}: {
  workspace: Workspace;
  size: number;
}) {
  return (
    <EntityAvatar
      size={size}
      variant="pigment"
      hue={deterministicHue(workspace.id)}
      alt={workspace.name}
      text={nameInitials(workspace.name)}
    />
  );
}

export function TeamSwitcher({ workspaces }: { workspaces: Workspace[] }) {
  const { isMobile } = useSidebar();
  const router = useRouter();
  const pathname = usePathname();
  const activeSlug = useWorkspaceSlug();
  const [isPending, startTransition] = React.useTransition();
  const [createOpen, setCreateOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const active =
    workspaces.find((workspace) => workspace.slug === activeSlug) ?? null;

  // The ids below the section belong to the workspace being left.
  const switchTo = (slug: string) => {
    if (slug === activeSlug) return;
    router.push(workspacePath(slug, workspaceSection(pathname)));
  };

  const create = () => {
    setError(null);
    startTransition(async () => {
      const result = await createWorkspaceAction(name);
      if (result.error !== undefined) {
        setError(result.error);
        return;
      }
      setName("");
      setCreateOpen(false);
      router.push(workspacePath(result.data.slug, WORKSPACE_HOME));
      router.refresh();
    });
  };

  // Before the first /v1/workspaces response there is nothing to switch
  // between; rendering a nameless button would just flash empty chrome.
  if (!active) {
    return null;
  }

  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <SidebarMenuButton
                size="lg"
                className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground transition-all duration-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <div className="flex aspect-square size-8 items-center justify-center bg-transparent">
                  <WorkspaceIcon workspace={active} size={32} />
                </div>
                <span className="flex-1 truncate text-left text-sm font-semibold leading-tight tracking-tight text-zinc-900 dark:text-zinc-100">
                  {active.name}
                </span>
                <ChevronsUpDown className="ml-auto text-zinc-400" />
              </SidebarMenuButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
              align="start"
              side={isMobile ? "bottom" : "right"}
              sideOffset={4}
            >
              <DropdownMenuLabel className="text-xs text-muted-foreground">
                Workspaces
              </DropdownMenuLabel>
              {workspaces.map((workspace) => (
                <DropdownMenuItem
                  key={workspace.id}
                  onClick={() => switchTo(workspace.slug)}
                  disabled={isPending}
                  className="gap-2 p-2 cursor-pointer"
                >
                  <div className="flex size-6 items-center justify-center">
                    <WorkspaceIcon workspace={workspace} size={24} />
                  </div>
                  <span className="flex-1 truncate">{workspace.name}</span>
                  {workspace.slug === activeSlug && (
                    <Check className="size-4 text-muted-foreground" />
                  )}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => {
                  setError(null);
                  setCreateOpen(true);
                }}
                className="gap-2 p-2 cursor-pointer"
              >
                <div className="flex size-6 items-center justify-center rounded-md border bg-primary/10">
                  <Plus className="size-4 text-primary" />
                </div>
                <span className="text-sm font-medium">Add workspace</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New workspace</DialogTitle>
            <DialogDescription>
              A workspace is an isolation boundary: its own members, budgets,
              policies and provider credentials. You can invite people into it
              from the Members page.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="workspace-name">Name</Label>
            <Input
              id="workspace-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && name.trim() && !isPending) {
                  create();
                }
              }}
              placeholder="Acme Inc"
              autoFocus
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setCreateOpen(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button onClick={create} disabled={isPending || !name.trim()}>
              {isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
