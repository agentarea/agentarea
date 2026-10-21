"use client";

// Import is only where a bundle comes from: pasted text, or `?src=<url>` from a
// link such as the landing page's "Install" button. What it creates is set up
// and started on the same plan the catalog uses (BundlePlan), so a bundle looks
// and installs the same whichever way it arrived.
import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronLeft, PackagePlus } from "lucide-react";
import type { ImportPreview } from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { BundlePlan } from "./BundlePlan";

type Origin = { source: string } | { sourceUrl: string };

export default function ImportWizard({
  initialSrc,
}: { initialSrc?: string } = {}) {
  const t = useTranslations("BundleInstall");
  const router = useWorkspaceRouter();
  const [text, setText] = useState("");
  const [origin, setOrigin] = useState<Origin | null>(
    initialSrc ? { sourceUrl: initialSrc } : null
  );
  const [preview, setPreview] = useState<ImportPreview | null>(null);

  function back() {
    // Leaving a linked bundle drops the link too, or the page would keep
    // offering to move it to another workspace above an empty paste box.
    if (initialSrc) {
      router.replace("/bundles/import");
      return;
    }
    setOrigin(null);
    setPreview(null);
  }

  if (origin) {
    const name = preview?.bundle.display_name || preview?.bundle.name;
    return (
      <div className="max-w-[1120px] space-y-6">
        <button
          onClick={back}
          className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
          {t("importBack")}
        </button>
        {name && (
          <div>
            <h2 className="text-xl font-semibold tracking-tight">
              {t("importTitle", { name })}
            </h2>
            {preview?.bundle.description && (
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                {preview.bundle.description}
              </p>
            )}
          </div>
        )}
        <BundlePlan
          source={"source" in origin ? origin.source : undefined}
          sourceUrl={"sourceUrl" in origin ? origin.sourceUrl : undefined}
          configuring
          onCancel={back}
          onLoaded={setPreview}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <div className="space-y-2 rounded-lg border border-border/60 bg-white p-6 dark:border-zinc-700/60 dark:bg-zinc-900">
        <div className="grid gap-2">
          <FormLabel htmlFor="package-source" icon={PackagePlus} required>
            {t("pasteLabel")}
          </FormLabel>
          <Textarea
            id="package-source"
            placeholder={t("pastePlaceholder")}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={12}
            className="font-mono text-xs"
          />
          <p className="note">{t("pasteHint")}</p>
        </div>
        <div className="flex justify-end pt-2">
          <Button
            onClick={() => setOrigin({ source: text.trim() })}
            disabled={!text.trim()}
          >
            {t("analyze")}
          </Button>
        </div>
      </div>
    </div>
  );
}
