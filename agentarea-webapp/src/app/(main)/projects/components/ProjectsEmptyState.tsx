"use client";

import { useState } from "react";
import EmptyState from "@/components/EmptyState";
import { CreateProjectDialog } from "./CreateProjectDialog";

/**
 * The empty state owns the dialog it opens, so the first project can be created
 * without leaving the list.
 */
export function ProjectsEmptyState() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <EmptyState
        title="No projects yet"
        description="A project scopes a slice of the workspace — its own agents, skills and connections — so separate lines of work stay apart."
        hints={[
          { text: "Add the agents that work on it" },
          { text: "Give it the skills and connections it may use" },
          { text: "Its files become shared context for the work inside it" },
        ]}
        iconsType="agent"
        action={{ label: "Create project", onClick: () => setOpen(true) }}
      />
      <CreateProjectDialog
        open={open}
        onOpenChange={setOpen}
        showTrigger={false}
      />
    </>
  );
}
