"use client";

import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function AccessControlHeaderControls() {
  // Rule creation flow is handled by the relationship rules card; this primary
  // action scrolls the inspector to the add-relationship affordance.
  const handleClick = () => {
    const target = document.getElementById("rebac-add-rule");
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  return (
    <Button size="sm" className="shrink-0 gap-2" onClick={handleClick}>
      <Plus className="h-4 w-4" />
      New rule
    </Button>
  );
}
