"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Check, CircleX, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Copy a text whole, a file's contents or an event's body. The icon answers
 * for a moment: a tick when it worked, a cross (and the reason in its label)
 * when the clipboard refused.
 */
export default function CopyContentsButton({ text }: { text: string }) {
  const t = useTranslations("FilesPage");
  const tCommon = useTranslations("Common");
  const [outcome, setOutcome] = useState<"copied" | "failed" | null>(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setOutcome("copied");
    } catch (err) {
      console.error("Failed to copy file contents", err);
      setOutcome("failed");
    }
    setTimeout(() => setOutcome(null), 2000);
  };

  const label =
    outcome === "copied"
      ? t("copied")
      : outcome === "failed"
        ? tCommon("copyFailed")
        : t("copyContents");

  return (
    <Button
      size="icon"
      variant="ghost"
      className="h-7 w-7 shrink-0 text-muted-foreground"
      aria-label={label}
      title={label}
      onClick={() => void copy()}
    >
      {outcome === "copied" ? (
        <Check className="h-4 w-4" />
      ) : outcome === "failed" ? (
        <CircleX className="h-4 w-4 text-destructive" />
      ) : (
        <Copy className="h-4 w-4" />
      )}
    </Button>
  );
}
