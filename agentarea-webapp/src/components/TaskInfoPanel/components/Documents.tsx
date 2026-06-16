import { useTranslations } from "next-intl";
import { Download, FileText } from "lucide-react";
import Section from "./Section";

interface DocumentsProps {
  artifacts?: unknown[];
}

interface DocItem {
  name: string;
  href?: string;
  meta?: string;
}

function toDocItem(artifact: unknown, index: number): DocItem {
  if (typeof artifact === "string") {
    return { name: artifact };
  }
  if (artifact && typeof artifact === "object") {
    const a = artifact as Record<string, any>;
    return {
      name: a.name || a.filename || a.title || `Artifact ${index + 1}`,
      href: a.url || a.uri || a.download_url || undefined,
      meta: a.mime_type || a.content_type || a.type || undefined,
    };
  }
  return { name: `Artifact ${index + 1}` };
}

export default function Documents({ artifacts }: DocumentsProps) {
  const t = useTranslations("TaskInfoPanel");

  if (!artifacts || artifacts.length === 0) {
    return null;
  }

  const docs = artifacts.map(toDocItem);

  return (
    <Section title={t("documents")} contentClassName="space-y-1.5 text-xs">
      {docs.map((doc, index) => (
        <div
          key={`${doc.name}-${index}`}
          className="flex items-center gap-2 px-0.5 py-1"
        >
          <FileText className="h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12px] font-medium text-foreground">
              {doc.name}
            </div>
            {doc.meta && (
              <div className="truncate text-[10px] text-muted-foreground">
                {doc.meta}
              </div>
            )}
          </div>
          {doc.href && (
            <a
              href={doc.href}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 text-muted-foreground transition-colors hover:text-primary"
              aria-label={`Download ${doc.name}`}
            >
              <Download className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      ))}
    </Section>
  );
}
