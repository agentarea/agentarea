import { useDocumentTheme } from "@modelcontextprotocol/ext-apps/react";
import type * as React from "react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

/** shadcn's Toaster, themed by the host's theme instead of next-themes. */
function Toaster({ ...props }: ToasterProps) {
  const theme = useDocumentTheme();
  return (
    <Sonner
      theme={theme}
      className="toaster group"
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
        } as React.CSSProperties
      }
      {...props}
    />
  );
}

export { Toaster };
