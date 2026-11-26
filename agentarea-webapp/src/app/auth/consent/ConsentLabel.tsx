"use client";

import { Globe, Layers, ShieldCheck } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";

// The page is a server component and cannot hand a lucide component to
// FormLabel across the boundary, so the icon is picked here by section.
const ICONS = { target: Globe, permissions: ShieldCheck, workspaces: Layers };

export function ConsentLabel({
  section,
  children,
}: {
  section: keyof typeof ICONS;
  children: React.ReactNode;
}) {
  return <FormLabel icon={ICONS[section]}>{children}</FormLabel>;
}
