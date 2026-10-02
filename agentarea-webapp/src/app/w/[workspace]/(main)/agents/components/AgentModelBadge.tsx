"use client";

import type { ComponentProps } from "react";
import ModelBadge from "@/components/ui/model-badge";

export default function AgentModelBadge(
  props: ComponentProps<typeof ModelBadge>
) {
  return <ModelBadge {...props} />;
}
