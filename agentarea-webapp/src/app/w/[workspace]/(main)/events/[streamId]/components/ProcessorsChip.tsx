"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

/** The stream's processors behind one chip, listed in a sheet. */
export default function ProcessorsChip({
  count,
  children,
}: {
  count: number;
  children: ReactNode;
}) {
  const t = useTranslations("EventsPage.processors");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        size="xs"
        variant="outline"
        className="px-2"
        onClick={() => setOpen(true)}
      >
        {t("chip", { count })}
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          aria-describedby={undefined}
          side="right"
          className="w-full overflow-y-auto sm:max-w-xl"
        >
          <SheetHeader>
            <SheetTitle>{t("title")}</SheetTitle>
          </SheetHeader>
          <div className="mt-4">{children}</div>
        </SheetContent>
      </Sheet>
    </>
  );
}
