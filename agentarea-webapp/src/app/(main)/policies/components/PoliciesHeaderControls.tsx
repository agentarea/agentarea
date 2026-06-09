"use client";

import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NEW_POLICY_EVENT } from "./PoliciesEditableView";

export default function PoliciesHeaderControls() {
  // The editor lives in the body (PoliciesEditableView). The page-level controls
  // slot is a separate React tree, so we bridge the click via a window event.
  const handleClick = () => {
    window.dispatchEvent(new CustomEvent(NEW_POLICY_EVENT));
  };

  return (
    <Button size="sm" className="shrink-0 gap-2" onClick={handleClick}>
      <Plus className="h-4 w-4" />
      New policy
    </Button>
  );
}
