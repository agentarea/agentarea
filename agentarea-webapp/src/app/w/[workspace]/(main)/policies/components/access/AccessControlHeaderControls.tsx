"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function AccessControlHeaderControls() {
  const t = useTranslations("PoliciesPage");

  // Rule creation flow is handled by the relationship rules card; this primary
  // action scrolls the inspector to the add-relationship affordance.
  const handleClick = () => {
    const target = document.getElementById("access-control-add-relationship");
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  return (
    <Button size="xs" className="shrink-0" onClick={handleClick}>
      <Plus />
      {t("newRule")}
    </Button>
  );
}
