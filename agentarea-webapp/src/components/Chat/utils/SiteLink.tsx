"use client";

import React, { useState } from "react";
import { Globe } from "lucide-react";
import { cn } from "@/lib/utils";

export type SiteLinkProps = Omit<React.ComponentProps<"a">, "href"> & {
  href: string;
};

function externalUrl(href: string): URL | null {
  try {
    const url = new URL(href);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

function readableUrl(url: URL): string {
  const path = url.pathname === "/" ? "" : url.pathname.replace(/\/$/, "");
  return `${url.hostname}${path}`;
}

function textContent(children: React.ReactNode): string {
  if (typeof children === "string" || typeof children === "number") {
    return String(children);
  }
  if (Array.isArray(children)) return children.map(textContent).join("");
  if (React.isValidElement(children)) {
    return textContent(
      (children.props as { children?: React.ReactNode }).children
    );
  }
  return "";
}

/** Web link with a favicon fetched directly from that site's own origin. */
export function SiteLink({
  href,
  children,
  className,
  target,
  rel,
  ...props
}: SiteLinkProps) {
  const url = externalUrl(href);
  const [faviconFailed, setFaviconFailed] = useState(false);
  const rawLabel = textContent(children).trim() === href;
  const label = rawLabel && url ? readableUrl(url) : children;

  return (
    <a
      href={href}
      target={target ?? (url ? "_blank" : undefined)}
      rel={rel ?? (url ? "noopener noreferrer" : undefined)}
      referrerPolicy={url ? "no-referrer" : undefined}
      className={cn(
        "inline-flex max-w-full items-baseline gap-1.5 text-sky-700 underline decoration-sky-700/35 underline-offset-2 hover:decoration-sky-700 dark:text-sky-400 dark:decoration-sky-400/40 dark:hover:decoration-sky-400",
        className
      )}
      {...props}
    >
      {url ? (
        faviconFailed ? (
          <Globe
            aria-hidden
            className="relative top-0.5 h-4 w-4 shrink-0 opacity-65"
          />
        ) : (
          // Fetch from the linked origin itself; no third-party URL aggregator.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`${url.origin}/favicon.ico`}
            alt=""
            aria-hidden
            width={16}
            height={16}
            loading="lazy"
            referrerPolicy="no-referrer"
            onError={() => setFaviconFailed(true)}
            className="relative top-0.5 h-4 w-4 shrink-0 rounded-[3px] object-contain"
          />
        )
      ) : null}
      <span className="min-w-0 break-all">{label}</span>
    </a>
  );
}

export default SiteLink;
