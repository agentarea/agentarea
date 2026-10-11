import { useTranslations } from "next-intl";
import { Download, FileText } from "lucide-react";
import { fileExtension } from "@/components/Chat/utils/fileIcon";
import { apiProxyUrl, isRelativeApiLink } from "@/lib/api-proxy-url";
import { cn } from "@/lib/utils";
import { formatFileSize } from "@/utils/fileUtils";
import Section from "./Section";

interface DocumentsProps {
  artifacts?: unknown[];
}

interface DocItem {
  name: string;
  href?: string;
  size?: number;
}

// A root-relative artifact link names an API path, reachable only through
// the proxy; anything else is an external link.
function toHref(url: string | undefined): string | undefined {
  return url && isRelativeApiLink(url) ? apiProxyUrl(url) : url;
}

function toDocItem(artifact: unknown, index: number): DocItem {
  if (typeof artifact === "string") {
    return { name: artifact };
  }
  if (artifact && typeof artifact === "object") {
    const a = artifact as Record<string, unknown>;
    return {
      name: `${a.name ?? a.filename ?? a.title ?? `Artifact ${index + 1}`}`,
      href: toHref((a.url ?? a.uri ?? a.download_url) as string | undefined),
      size: typeof a.size === "number" ? a.size : undefined,
    };
  }
  return { name: `Artifact ${index + 1}` };
}

/**
 * The files the task published. A row that can be downloaded is a link as a
 * whole, lit on hover like the panel's other rows, rather than a row with one
 * small icon to aim at.
 */
export default function Documents({ artifacts }: DocumentsProps) {
  const t = useTranslations("TaskInfoPanel");

  if (!artifacts || artifacts.length === 0) {
    return null;
  }

  const docs = artifacts.map(toDocItem);
  const rowClassName = "-mx-1.5 flex items-center gap-2 rounded-md px-1.5 py-1";

  return (
    <Section title={t("documents")} contentClassName="space-y-0.5 text-xs">
      {docs.map((doc, index) => {
        // The extension, not a type name: it reads the same in any language.
        const meta = [
          fileExtension(doc.name)?.toUpperCase(),
          doc.size !== undefined ? formatFileSize(doc.size) : null,
        ]
          .filter(Boolean)
          .join(" · ");
        const body = (
          <>
            <FileText className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12px] font-medium text-foreground">
                {doc.name}
              </span>
              <span className="block truncate text-[10px] text-muted-foreground">
                {meta}
              </span>
            </span>
          </>
        );
        const key = `${doc.name}-${index}`;

        if (!doc.href) {
          return (
            <div key={key} className={rowClassName}>
              {body}
            </div>
          );
        }

        const label = t("downloadFile", { name: doc.name });
        return (
          <a
            key={key}
            href={doc.href}
            download={doc.name}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={label}
            title={label}
            className={cn(
              rowClassName,
              "group/doc transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
          >
            {body}
            <Download
              aria-hidden
              className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-colors group-hover/doc:text-primary"
            />
          </a>
        );
      })}
    </Section>
  );
}
