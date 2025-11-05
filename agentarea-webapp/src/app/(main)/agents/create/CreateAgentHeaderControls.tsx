"use client";

import React from "react";
import { Button } from "@/components/ui/button";

export default function CreateAgentHeaderControls({
  label,
}: {
  label?: string;
}) {
  return (
    <div className="flex items-center gap-2 py-1">
      <Button size="xs" type="submit" form="agent-form">
        {label}
      </Button>
    </div>
  );
}


