"use client";

import Link from "@/components/WorkspaceLink";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function PoliciesHeaderControls() {
  return (
    <Button size="sm" className="shrink-0 gap-2" asChild>
      <Link href="/policies/new">
        <Plus />
        New policy
      </Link>
    </Button>
  );
}
